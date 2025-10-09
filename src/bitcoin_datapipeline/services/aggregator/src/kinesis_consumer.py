"""Kinesis consumer for reading real-time market data streams."""

import asyncio
import logging
import json
import time
from datetime import datetime
from typing import Dict, Any, List, Optional, AsyncIterator
import boto3
from botocore.exceptions import ClientError

from .config.settings import AggregatorConfig


logger = logging.getLogger(__name__)


class KinesisConsumer:
    """Consumes messages from Kinesis Data Streams."""
    
    def __init__(self, config: AggregatorConfig):
        self.config = config
        
        # Initialize Kinesis client
        session = boto3.Session()
        self.kinesis_client = session.client(
            'kinesis',
            region_name=config.aws.region,
            endpoint_url=config.aws.endpoint_url
        )
        
        # Consumer state
        self._running = False
        self._shard_iterators = {}
        self._last_sequence_numbers = {}
        
        # Statistics
        self.stats = {
            "records_consumed": 0,
            "shards_active": 0,
            "connection_errors": 0,
            "last_record_time": None
        }
        
        logger.info(f"KinesisConsumer initialized for streams: {list(config.kinesis.streams.values())}")
    
    async def start(self):
        """Start the Kinesis consumer."""
        self._running = True
        logger.info("Starting Kinesis consumer")
        
        # Initialize shard iterators for all streams
        for stream_type, stream_name in self.config.kinesis.streams.items():
            await self._initialize_stream_shards(stream_name)
        
        self.stats["shards_active"] = len(self._shard_iterators)
        logger.info(f"Initialized {self.stats['shards_active']} shard iterators")
    
    async def stop(self):
        """Stop the Kinesis consumer."""
        logger.info("Stopping Kinesis consumer")
        self._running = False
        
        # Clear shard iterators
        self._shard_iterators.clear()
        self._last_sequence_numbers.clear()
    
    async def _initialize_stream_shards(self, stream_name: str):
        """Initialize shard iterators for a stream."""
        try:
            # Get stream description
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.kinesis_client.describe_stream(StreamName=stream_name)
            )
            
            stream_description = response['StreamDescription']
            shards = stream_description['Shards']
            
            logger.info(f"Found {len(shards)} shards for stream {stream_name}")
            
            # Initialize iterator for each shard
            for shard in shards:
                shard_id = shard['ShardId']
                
                # Get shard iterator starting from latest
                iterator_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.kinesis_client.get_shard_iterator(
                        StreamName=stream_name,
                        ShardId=shard_id,
                        ShardIteratorType='LATEST'
                    )
                )
                
                shard_iterator = iterator_response['ShardIterator']
                iterator_key = f"{stream_name}:{shard_id}"
                
                self._shard_iterators[iterator_key] = {
                    "iterator": shard_iterator,
                    "stream_name": stream_name,
                    "shard_id": shard_id,
                    "last_activity": time.time()
                }
                
                logger.debug(f"Initialized shard iterator for {iterator_key}")
        
        except Exception as e:
            logger.error(f"Error initializing shards for stream {stream_name}: {e}")
            self.stats["connection_errors"] += 1
            raise
    
    async def consume_messages(self) -> AsyncIterator[Dict[str, Any]]:
        """Consume messages from all Kinesis streams."""
        while self._running:
            try:
                # Process each shard iterator
                for iterator_key, iterator_info in list(self._shard_iterators.items()):
                    if not self._running:
                        break
                    
                    try:
                        # Get records from shard
                        records = await self._get_records_from_shard(iterator_key, iterator_info)
                        
                        # Yield each record
                        for record in records:
                            if not self._running:
                                break
                            yield record
                    
                    except Exception as e:
                        logger.warning(f"Error processing shard {iterator_key}: {e}")
                        # Try to refresh the shard iterator
                        await self._refresh_shard_iterator(iterator_key, iterator_info)
                
                # Small delay to prevent busy waiting
                await asyncio.sleep(self.config.kinesis.polling_interval_seconds)
            
            except Exception as e:
                logger.error(f"Error in consume_messages loop: {e}", exc_info=True)
                self.stats["connection_errors"] += 1
                await asyncio.sleep(5)  # Wait before retrying
    
    async def _get_records_from_shard(
        self, 
        iterator_key: str, 
        iterator_info: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Get records from a specific shard."""
        
        shard_iterator = iterator_info["iterator"]
        stream_name = iterator_info["stream_name"]
        
        if not shard_iterator:
            return []
        
        try:
            # Get records from Kinesis
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.kinesis_client.get_records(
                    ShardIterator=shard_iterator,
                    Limit=self.config.kinesis.max_records_per_request
                )
            )
            
            records = response.get('Records', [])
            next_iterator = response.get('NextShardIterator')
            
            # Update iterator
            iterator_info["iterator"] = next_iterator
            iterator_info["last_activity"] = time.time()
            
            # Process records
            processed_records = []
            
            for record in records:
                try:
                    # Decode record data
                    data = json.loads(record['Data'].decode('utf-8'))
                    
                    processed_record = {
                        "stream_name": stream_name,
                        "partition_key": record['PartitionKey'],
                        "sequence_number": record['SequenceNumber'],
                        "data": data,
                        "approximate_arrival_timestamp": record.get('ApproximateArrivalTimestamp'),
                        "processing_timestamp": datetime.now()
                    }
                    
                    processed_records.append(processed_record)
                    
                    # Update statistics
                    self.stats["records_consumed"] += 1
                    self.stats["last_record_time"] = datetime.now()
                    
                    # Store last sequence number for resumption
                    self._last_sequence_numbers[iterator_key] = record['SequenceNumber']
                
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON in Kinesis record: {e}")
                except Exception as e:
                    logger.warning(f"Error processing Kinesis record: {e}")
            
            if processed_records:
                logger.debug(f"Retrieved {len(processed_records)} records from {iterator_key}")
            
            return processed_records
        
        except ClientError as e:
            error_code = e.response['Error']['Code']
            
            if error_code == 'ExpiredIteratorException':
                logger.info(f"Shard iterator expired for {iterator_key}, refreshing")
                await self._refresh_shard_iterator(iterator_key, iterator_info)
            elif error_code == 'ProvisionedThroughputExceededException':
                logger.warning(f"Throughput exceeded for {iterator_key}, backing off")
                await asyncio.sleep(2)
            else:
                logger.error(f"Kinesis error for {iterator_key}: {error_code}")
                self.stats["connection_errors"] += 1
            
            return []
        
        except Exception as e:
            logger.error(f"Unexpected error getting records from {iterator_key}: {e}")
            self.stats["connection_errors"] += 1
            return []
    
    async def _refresh_shard_iterator(self, iterator_key: str, iterator_info: Dict[str, Any]):
        """Refresh an expired shard iterator."""
        
        stream_name = iterator_info["stream_name"]
        shard_id = iterator_info["shard_id"]
        
        try:
            # Try to resume from last sequence number if available
            last_seq = self._last_sequence_numbers.get(iterator_key)
            
            if last_seq:
                # Resume from after the last processed record
                iterator_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.kinesis_client.get_shard_iterator(
                        StreamName=stream_name,
                        ShardId=shard_id,
                        ShardIteratorType='AFTER_SEQUENCE_NUMBER',
                        StartingSequenceNumber=last_seq
                    )
                )
            else:
                # Start from latest
                iterator_response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.kinesis_client.get_shard_iterator(
                        StreamName=stream_name,
                        ShardId=shard_id,
                        ShardIteratorType='LATEST'
                    )
                )
            
            iterator_info["iterator"] = iterator_response['ShardIterator']
            iterator_info["last_activity"] = time.time()
            
            logger.info(f"Refreshed shard iterator for {iterator_key}")
        
        except Exception as e:
            logger.error(f"Failed to refresh shard iterator for {iterator_key}: {e}")
            # Remove failed iterator
            self._shard_iterators.pop(iterator_key, None)
            self.stats["connection_errors"] += 1
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Kinesis consumer."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "running": self._running,
            "stats": self.stats.copy()
        }
        
        # Check active shard iterators
        active_iterators = sum(
            1 for info in self._shard_iterators.values() 
            if info.get("iterator") is not None
        )
        
        health_status["active_shard_iterators"] = active_iterators
        
        if active_iterators == 0 and self._running:
            health_status["status"] = "unhealthy"
            health_status["error"] = "No active shard iterators"
        
        # Check recent activity
        if self.stats["last_record_time"]:
            time_since_last = (
                datetime.now() - self.stats["last_record_time"]
            ).total_seconds()
            
            if time_since_last > 300:  # No records for 5 minutes
                health_status["status"] = "degraded"
                health_status["warning"] = f"No records for {time_since_last:.0f} seconds"
        
        # Check error rate
        if self.stats["records_consumed"] > 0:
            error_rate = self.stats["connection_errors"] / max(self.stats["records_consumed"], 1)
            if error_rate > 0.1:  # >10% error rate
                health_status["status"] = "degraded"
                health_status["warning"] = f"High error rate: {error_rate:.2%}"
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get consumer statistics."""
        return {
            **self.stats,
            "active_iterators": len(self._shard_iterators),
            "streams_configured": len(self.config.kinesis.streams)
        }