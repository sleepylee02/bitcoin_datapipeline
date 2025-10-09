"""AWS Kinesis Data Streams client for real-time data streaming."""

import asyncio
import logging
import time
import json
import hashlib
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict, deque

import aioboto3
from botocore.exceptions import ClientError

from ..config.aws_config import AWSClientManager
from ..config.settings import AWSConfig
from ..utils.retry import retry_with_backoff, CircuitBreaker

logger = logging.getLogger(__name__)


@dataclass
class KinesisRecord:
    """Kinesis record wrapper."""
    stream_name: str
    partition_key: str
    data: bytes
    explicit_hash_key: Optional[str] = None
    timestamp: Optional[float] = None


@dataclass
class BatchStats:
    """Statistics for batch operations."""
    records_sent: int = 0
    records_failed: int = 0
    bytes_sent: int = 0
    latency_ms: float = 0.0
    last_batch_time: Optional[float] = None


class KinesisProducer:
    """
    High-performance Kinesis producer with batching and retry logic.
    
    Features:
    - Automatic batching with configurable size and time limits
    - Per-stream partition key distribution
    - Retry with exponential backoff
    - Circuit breaker protection
    - Comprehensive metrics
    """
    
    def __init__(self, aws_client_manager: AWSClientManager, config: AWSConfig):
        self.aws_client_manager = aws_client_manager
        self.config = config
        
        # Batching configuration
        self.batch_size = config.kinesis_batch_size
        self.flush_interval = config.kinesis_flush_interval_seconds
        
        # Internal state
        self._batches: Dict[str, List[KinesisRecord]] = defaultdict(list)
        self._batch_stats: Dict[str, BatchStats] = defaultdict(BatchStats)
        self._last_flush_time = time.time()
        self._running = False
        self._flush_task: Optional[asyncio.Task] = None
        
        # Circuit breakers per stream
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        
        # Metrics
        self.stats = {
            'total_records': 0,
            'total_bytes': 0,
            'failed_records': 0,
            'batches_sent': 0,
            'errors': 0,
            'circuit_breaker_opens': 0
        }
        
        logger.info(f"Initialized KinesisProducer with batch_size={self.batch_size}")
    
    async def start(self):
        """Start the producer with background flush task."""
        if self._running:
            return
        
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info("KinesisProducer started")
    
    async def stop(self):
        """Stop the producer and flush remaining records."""
        if not self._running:
            return
        
        self._running = False
        
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        
        # Flush any remaining records
        await self._flush_all_batches()
        logger.info("KinesisProducer stopped")
    
    async def put_record(
        self,
        stream_name: str,
        data: Dict[str, Any],
        partition_key: Optional[str] = None
    ) -> bool:
        """
        Add a record to the batch for the specified stream.
        
        Args:
            stream_name: Kinesis stream name
            data: Record data (will be JSON serialized)
            partition_key: Optional partition key (auto-generated if not provided)
        
        Returns:
            True if record was added successfully
        """
        if not self._running:
            logger.warning("Producer not running, dropping record")
            return False
        
        try:
            # Serialize data
            data_bytes = json.dumps(data, separators=(',', ':')).encode('utf-8')
            
            # Generate partition key if not provided
            if not partition_key:
                partition_key = self._generate_partition_key(data)
            
            # Create record
            record = KinesisRecord(
                stream_name=stream_name,
                partition_key=partition_key,
                data=data_bytes,
                timestamp=time.time()
            )
            
            # Add to batch
            self._batches[stream_name].append(record)
            
            # Check if we need to flush this stream
            if len(self._batches[stream_name]) >= self.batch_size:
                await self._flush_stream(stream_name)
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to add record to batch: {e}")
            self.stats['errors'] += 1
            return False
    
    async def put_trade_record(self, trade_data: Dict[str, Any]) -> bool:
        """Put a trade record to the trade stream."""
        return await self.put_record(
            stream_name=self.config.kinesis_trade_stream,
            data=trade_data,
            partition_key=trade_data.get('symbol', 'default')
        )
    
    async def put_bba_record(self, bba_data: Dict[str, Any]) -> bool:
        """Put a best bid/ask record to the BBA stream."""
        return await self.put_record(
            stream_name=self.config.kinesis_bba_stream,
            data=bba_data,
            partition_key=bba_data.get('symbol', 'default')
        )
    
    async def put_depth_record(self, depth_data: Dict[str, Any]) -> bool:
        """Put a depth record to the depth stream."""
        return await self.put_record(
            stream_name=self.config.kinesis_depth_stream,
            data=depth_data,
            partition_key=depth_data.get('symbol', 'default')
        )
    
    async def _flush_loop(self):
        """Background task to flush batches periodically."""
        while self._running:
            try:
                await asyncio.sleep(self.flush_interval)
                
                current_time = time.time()
                if current_time - self._last_flush_time >= self.flush_interval:
                    await self._flush_all_batches()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in flush loop: {e}")
                await asyncio.sleep(1)  # Brief pause before retrying
    
    async def _flush_all_batches(self):
        """Flush all pending batches."""
        streams_to_flush = list(self._batches.keys())
        
        if streams_to_flush:
            logger.debug(f"Flushing {len(streams_to_flush)} streams")
            
            # Flush all streams concurrently
            flush_tasks = [
                self._flush_stream(stream_name)
                for stream_name in streams_to_flush
            ]
            
            if flush_tasks:
                await asyncio.gather(*flush_tasks, return_exceptions=True)
        
        self._last_flush_time = time.time()
    
    async def _flush_stream(self, stream_name: str):
        """Flush pending records for a specific stream."""
        if stream_name not in self._batches or not self._batches[stream_name]:
            return
        
        records = self._batches[stream_name].copy()
        self._batches[stream_name].clear()
        
        if not records:
            return
        
        # Get circuit breaker for this stream
        if stream_name not in self._circuit_breakers:
            self._circuit_breakers[stream_name] = CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=30.0,
                expected_exception=ClientError
            )
        
        circuit_breaker = self._circuit_breakers[stream_name]
        
        try:
            start_time = time.time()
            
            # Send batch through circuit breaker
            await circuit_breaker.call(self._send_batch, stream_name, records)
            
            # Update stats
            batch_stats = self._batch_stats[stream_name]
            batch_stats.records_sent += len(records)
            batch_stats.bytes_sent += sum(len(r.data) for r in records)
            batch_stats.latency_ms = (time.time() - start_time) * 1000
            batch_stats.last_batch_time = time.time()
            
            self.stats['total_records'] += len(records)
            self.stats['total_bytes'] += sum(len(r.data) for r in records)
            self.stats['batches_sent'] += 1
            
            logger.debug(f"Flushed {len(records)} records to {stream_name}")
            
        except Exception as e:
            logger.error(f"Failed to flush batch to {stream_name}: {e}")
            
            # Re-queue failed records (with limit to prevent infinite growth)
            if len(self._batches[stream_name]) < 1000:
                self._batches[stream_name].extend(records)
            else:
                logger.warning(f"Dropping {len(records)} records due to queue overflow")
            
            self.stats['failed_records'] += len(records)
            self.stats['errors'] += 1
            
            if circuit_breaker.state == 'OPEN':
                self.stats['circuit_breaker_opens'] += 1
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=0.1,
        max_delay=5.0,
        exceptions=(ClientError,)
    )
    async def _send_batch(self, stream_name: str, records: List[KinesisRecord]):
        """Send a batch of records to Kinesis with retry logic."""
        
        if not records:
            return
        
        # Prepare records for Kinesis API
        kinesis_records = []
        for record in records:
            kinesis_record = {
                'Data': record.data,
                'PartitionKey': record.partition_key
            }
            
            if record.explicit_hash_key:
                kinesis_record['ExplicitHashKey'] = record.explicit_hash_key
            
            kinesis_records.append(kinesis_record)
        
        # Send to Kinesis
        kinesis_client = self.aws_client_manager.kinesis_client
        
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: kinesis_client.put_records(
                StreamName=stream_name,
                Records=kinesis_records
            )
        )
        
        # Handle partial failures
        failed_record_count = response.get('FailedRecordCount', 0)
        if failed_record_count > 0:
            logger.warning(f"Kinesis batch had {failed_record_count} failed records")
            
            # Extract failed records for retry
            failed_records = []
            for i, record_result in enumerate(response.get('Records', [])):
                if 'ErrorCode' in record_result:
                    failed_records.append(records[i])
                    logger.warning(
                        f"Record failed: {record_result.get('ErrorCode')} - "
                        f"{record_result.get('ErrorMessage')}"
                    )
            
            if failed_records:
                # Re-queue failed records for retry
                self._batches[stream_name].extend(failed_records)
                raise ClientError(
                    error_response={'Error': {'Code': 'PartialFailure'}},
                    operation_name='PutRecords'
                )
        
        logger.debug(f"Successfully sent {len(records)} records to {stream_name}")
    
    def _generate_partition_key(self, data: Dict[str, Any]) -> str:
        """Generate a partition key for even distribution."""
        # Use symbol if available, otherwise hash the data
        if 'symbol' in data:
            return data['symbol']
        
        # Hash the data for distribution
        data_str = json.dumps(data, sort_keys=True)
        return hashlib.md5(data_str.encode()).hexdigest()[:16]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get producer statistics."""
        stream_stats = {}
        for stream_name, stats in self._batch_stats.items():
            stream_stats[stream_name] = asdict(stats)
        
        return {
            'overall': self.stats,
            'streams': stream_stats,
            'queue_sizes': {
                stream: len(records)
                for stream, records in self._batches.items()
            },
            'circuit_breakers': {
                stream: cb.state
                for stream, cb in self._circuit_breakers.items()
            }
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Kinesis producer."""
        stats = self.get_stats()
        
        health_status = {
            'healthy': True,
            'issues': []
        }
        
        # Check if producer is running
        if not self._running:
            health_status['healthy'] = False
            health_status['issues'].append('Producer not running')
        
        # Check circuit breaker states
        for stream, state in stats['circuit_breakers'].items():
            if state == 'OPEN':
                health_status['healthy'] = False
                health_status['issues'].append(f'Circuit breaker open for {stream}')
        
        # Check queue sizes
        for stream, queue_size in stats['queue_sizes'].items():
            if queue_size > 1000:
                health_status['healthy'] = False
                health_status['issues'].append(f'Large queue for {stream}: {queue_size}')
        
        # Check error rates
        if stats['overall']['total_records'] > 0:
            error_rate = stats['overall']['failed_records'] / stats['overall']['total_records']
            if error_rate > 0.05:  # >5% error rate
                health_status['healthy'] = False
                health_status['issues'].append(f'High error rate: {error_rate:.2%}')
        
        return {
            'status': 'healthy' if health_status['healthy'] else 'unhealthy',
            'issues': health_status['issues'],
            'stats': stats
        }