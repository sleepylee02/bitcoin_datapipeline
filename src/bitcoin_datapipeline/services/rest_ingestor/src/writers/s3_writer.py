"""S3 Bronze layer writer for historical data storage."""

import asyncio
import logging
import json
import gzip
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path
import io
from dataclasses import dataclass

from ..config.aws_config import AWSClientManager
from ..config.settings import AWSConfig
from ..utils.retry import retry_with_backoff
from ..utils.deduplication import RecordDeduplicator

logger = logging.getLogger(__name__)


@dataclass
class S3WriteStats:
    """Statistics for S3 write operations."""
    files_written: int = 0
    records_written: int = 0
    bytes_written: int = 0
    errors: int = 0
    last_write_time: Optional[float] = None


class S3BronzeWriter:
    """
    S3 Bronze layer writer for storing raw market data.
    
    Features:
    - Time-partitioned storage (yyyy/mm/dd/hh structure)
    - JSONL format with optional gzip compression
    - Deduplication support
    - Batch writing for efficiency
    - Proper error handling and retry logic
    """
    
    def __init__(self, aws_client_manager: AWSClientManager, config: AWSConfig):
        self.aws_client_manager = aws_client_manager
        self.config = config
        self.deduplicator = RecordDeduplicator()
        
        # Statistics
        self.stats = S3WriteStats()
        
        # Configuration
        self.compression_enabled = True
        self.batch_size = 1000
        self.buffer_timeout_seconds = 300  # 5 minutes
        
        # Internal buffering
        self._buffers: Dict[str, List[Dict[str, Any]]] = {}
        self._buffer_timestamps: Dict[str, float] = {}
        
        logger.info("S3BronzeWriter initialized")
    
    async def write_agg_trades(
        self,
        symbol: str,
        trades: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Write aggregated trades to S3 bronze layer."""
        
        if not trades:
            return True
        
        timestamp = timestamp or datetime.utcnow()
        
        # Build S3 key with time partitioning
        s3_key = self._build_s3_key(
            data_type="aggTrades",
            symbol=symbol,
            timestamp=timestamp
        )
        
        # Deduplicate trades
        unique_trades = []
        for trade in trades:
            trade_id = f"{trade.get('symbol', symbol)}_{trade.get('trade_id', trade.get('a'))}"
            if self.deduplicator.is_unique(trade_id, trade.get('event_ts', 0)):
                unique_trades.append(trade)
        
        if not unique_trades:
            logger.debug(f"No unique trades to write for {symbol}")
            return True
        
        logger.info(f"Writing {len(unique_trades)} unique aggTrades for {symbol} to {s3_key}")
        
        return await self._write_jsonl_to_s3(s3_key, unique_trades)
    
    async def write_trades(
        self,
        symbol: str,
        trades: List[Dict[str, Any]],
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Write individual trades to S3 bronze layer."""
        
        if not trades:
            return True
        
        timestamp = timestamp or datetime.utcnow()
        
        s3_key = self._build_s3_key(
            data_type="trades",
            symbol=symbol,
            timestamp=timestamp
        )
        
        # Deduplicate trades
        unique_trades = []
        for trade in trades:
            trade_id = f"{trade.get('symbol', symbol)}_{trade.get('trade_id', trade.get('id'))}"
            if self.deduplicator.is_unique(trade_id, trade.get('event_ts', 0)):
                unique_trades.append(trade)
        
        if not unique_trades:
            logger.debug(f"No unique trades to write for {symbol}")
            return True
        
        logger.info(f"Writing {len(unique_trades)} unique trades for {symbol} to {s3_key}")
        
        return await self._write_jsonl_to_s3(s3_key, unique_trades)
    
    async def write_klines(
        self,
        symbol: str,
        klines: List[List[Any]],
        interval: str = "1m",
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Write kline data to S3 bronze layer."""
        
        if not klines:
            return True
        
        timestamp = timestamp or datetime.utcnow()
        
        s3_key = self._build_s3_key(
            data_type=f"klines_{interval}",
            symbol=symbol,
            timestamp=timestamp
        )
        
        # Convert klines to structured format
        structured_klines = []
        for kline in klines:
            if len(kline) >= 12:  # Standard Binance kline format
                structured_kline = {
                    "open_time": kline[0],
                    "open_price": float(kline[1]),
                    "high_price": float(kline[2]),
                    "low_price": float(kline[3]),
                    "close_price": float(kline[4]),
                    "volume": float(kline[5]),
                    "close_time": kline[6],
                    "quote_volume": float(kline[7]),
                    "trade_count": kline[8],
                    "taker_buy_base_volume": float(kline[9]),
                    "taker_buy_quote_volume": float(kline[10]),
                    "symbol": symbol,
                    "interval": interval,
                    "ingest_ts": int(datetime.utcnow().timestamp() * 1000)
                }
                
                # Deduplicate by open_time
                kline_id = f"{symbol}_{interval}_{kline[0]}"
                if self.deduplicator.is_unique(kline_id, kline[0]):
                    structured_klines.append(structured_kline)
        
        if not structured_klines:
            logger.debug(f"No unique klines to write for {symbol}")
            return True
        
        logger.info(f"Writing {len(structured_klines)} unique klines for {symbol} to {s3_key}")
        
        return await self._write_jsonl_to_s3(s3_key, structured_klines)
    
    async def write_depth_snapshot(
        self,
        symbol: str,
        depth_data: Dict[str, Any],
        timestamp: Optional[datetime] = None
    ) -> bool:
        """Write depth snapshot to S3 bronze layer."""
        
        timestamp = timestamp or datetime.utcnow()
        
        s3_key = self._build_s3_key(
            data_type="depth_snapshots",
            symbol=symbol,
            timestamp=timestamp
        )
        
        # Structure depth data
        structured_depth = {
            "symbol": symbol,
            "timestamp": int(timestamp.timestamp() * 1000),
            "ingest_ts": int(datetime.utcnow().timestamp() * 1000),
            "last_update_id": depth_data.get("lastUpdateId"),
            "bids": depth_data.get("bids", []),
            "asks": depth_data.get("asks", []),
            "source": "rest"
        }
        
        logger.info(f"Writing depth snapshot for {symbol} to {s3_key}")
        
        return await self._write_jsonl_to_s3(s3_key, [structured_depth])
    
    def _build_s3_key(self, data_type: str, symbol: str, timestamp: datetime) -> str:
        """Build S3 key with time partitioning."""
        
        # Time partitioning: yyyy/mm/dd/hh
        year = timestamp.strftime("%Y")
        month = timestamp.strftime("%m")
        day = timestamp.strftime("%d")
        hour = timestamp.strftime("%H")
        
        # File name with timestamp
        filename = f"{data_type}_{timestamp.strftime('%Y%m%d_%H%M%S')}.jsonl"
        if self.compression_enabled:
            filename += ".gz"
        
        return f"{self.config.s3_bronze_prefix}/{symbol}/{data_type}/yyyy={year}/mm={month}/dd={day}/hh={hour}/{filename}"
    
    @retry_with_backoff(
        max_attempts=3,
        initial_delay=1.0,
        max_delay=10.0,
        exceptions=(Exception,)
    )
    async def _write_jsonl_to_s3(self, s3_key: str, records: List[Dict[str, Any]]) -> bool:
        """Write records to S3 as JSONL format with optional compression."""
        
        try:
            # Convert records to JSONL
            jsonl_data = []
            for record in records:
                jsonl_data.append(json.dumps(record, separators=(',', ':')))
            
            jsonl_content = '\n'.join(jsonl_data) + '\n'
            
            # Apply compression if enabled
            if self.compression_enabled:
                buffer = io.BytesIO()
                with gzip.GzipFile(fileobj=buffer, mode='wb') as gz_file:
                    gz_file.write(jsonl_content.encode('utf-8'))
                content_bytes = buffer.getvalue()
                content_type = 'application/gzip'
            else:
                content_bytes = jsonl_content.encode('utf-8')
                content_type = 'application/json'
            
            # Upload to S3
            s3_client = self.aws_client_manager.s3_client
            
            await asyncio.get_event_loop().run_in_executor(\n                None,\n                lambda: s3_client.put_object(\n                    Bucket=self.config.s3_bucket,\n                    Key=s3_key,\n                    Body=content_bytes,\n                    ContentType=content_type,\n                    ContentEncoding='gzip' if self.compression_enabled else None,\n                    Metadata={\n                        'record_count': str(len(records)),\n                        'ingest_timestamp': str(int(datetime.utcnow().timestamp())),\n                        'compression': 'gzip' if self.compression_enabled else 'none'\n                    }\n                )\n            )\n            \n            # Update statistics\n            self.stats.files_written += 1\n            self.stats.records_written += len(records)\n            self.stats.bytes_written += len(content_bytes)\n            self.stats.last_write_time = datetime.utcnow().timestamp()\n            \n            logger.info(\n                f\"Successfully wrote {len(records)} records to s3://{self.config.s3_bucket}/{s3_key} \"\n                f\"({len(content_bytes)} bytes)\"\n            )\n            \n            return True\n            \n        except Exception as e:\n            logger.error(f\"Failed to write to S3 key {s3_key}: {e}\")\n            self.stats.errors += 1\n            raise\n    \n    async def write_buffered(self, buffer_key: str, record: Dict[str, Any]):\n        \"\"\"Add record to buffer and write when buffer is full or timeout reached.\"\"\"\n        \n        current_time = datetime.utcnow().timestamp()\n        \n        # Initialize buffer if needed\n        if buffer_key not in self._buffers:\n            self._buffers[buffer_key] = []\n            self._buffer_timestamps[buffer_key] = current_time\n        \n        self._buffers[buffer_key].append(record)\n        \n        # Check if we should flush the buffer\n        should_flush = (\n            len(self._buffers[buffer_key]) >= self.batch_size or\n            current_time - self._buffer_timestamps[buffer_key] >= self.buffer_timeout_seconds\n        )\n        \n        if should_flush:\n            await self._flush_buffer(buffer_key)\n    \n    async def _flush_buffer(self, buffer_key: str):\n        \"\"\"Flush a specific buffer to S3.\"\"\"\n        \n        if buffer_key not in self._buffers or not self._buffers[buffer_key]:\n            return\n        \n        records = self._buffers[buffer_key].copy()\n        self._buffers[buffer_key].clear()\n        self._buffer_timestamps[buffer_key] = datetime.utcnow().timestamp()\n        \n        # Parse buffer key to extract metadata\n        # Format: \"symbol_datatype_timestamp\"\n        try:\n            parts = buffer_key.split('_')\n            symbol = parts[0]\n            data_type = '_'.join(parts[1:-1])\n            \n            timestamp = datetime.utcnow()\n            s3_key = self._build_s3_key(data_type, symbol, timestamp)\n            \n            await self._write_jsonl_to_s3(s3_key, records)\n            \n        except Exception as e:\n            logger.error(f\"Failed to flush buffer {buffer_key}: {e}\")\n            # Re-add records to buffer for retry\n            self._buffers[buffer_key].extend(records)\n    \n    async def flush_all_buffers(self):\n        \"\"\"Flush all pending buffers.\"\"\"\n        \n        buffer_keys = list(self._buffers.keys())\n        \n        if buffer_keys:\n            logger.info(f\"Flushing {len(buffer_keys)} buffers\")\n            \n            flush_tasks = [\n                self._flush_buffer(buffer_key)\n                for buffer_key in buffer_keys\n                if self._buffers[buffer_key]  # Only flush non-empty buffers\n            ]\n            \n            if flush_tasks:\n                await asyncio.gather(*flush_tasks, return_exceptions=True)\n    \n    def get_stats(self) -> Dict[str, Any]:\n        \"\"\"Get S3 writer statistics.\"\"\"\n        \n        return {\n            'files_written': self.stats.files_written,\n            'records_written': self.stats.records_written,\n            'bytes_written': self.stats.bytes_written,\n            'errors': self.stats.errors,\n            'last_write_time': self.stats.last_write_time,\n            'buffer_counts': {\n                buffer_key: len(records)\n                for buffer_key, records in self._buffers.items()\n            },\n            'deduplication_stats': self.deduplicator.get_stats()\n        }\n    \n    async def health_check(self) -> Dict[str, Any]:\n        \"\"\"Perform health check on S3 writer.\"\"\"\n        \n        stats = self.get_stats()\n        \n        health_status = {\n            'healthy': True,\n            'issues': []\n        }\n        \n        # Check error rates\n        if stats['files_written'] > 0:\n            error_rate = stats['errors'] / stats['files_written']\n            if error_rate > 0.05:  # >5% error rate\n                health_status['healthy'] = False\n                health_status['issues'].append(f'High error rate: {error_rate:.2%}')\n        \n        # Check buffer sizes\n        total_buffered = sum(stats['buffer_counts'].values())\n        if total_buffered > 10000:\n            health_status['healthy'] = False\n            health_status['issues'].append(f'Large buffer size: {total_buffered}')\n        \n        # Check last write time\n        if stats['last_write_time']:\n            time_since_last_write = datetime.utcnow().timestamp() - stats['last_write_time']\n            if time_since_last_write > 3600:  # >1 hour\n                health_status['healthy'] = False\n                health_status['issues'].append(f'No writes for {time_since_last_write/3600:.1f} hours')\n        \n        return {\n            'status': 'healthy' if health_status['healthy'] else 'unhealthy',\n            'issues': health_status['issues'],\n            'stats': stats\n        }"