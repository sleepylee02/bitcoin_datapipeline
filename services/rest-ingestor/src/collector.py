"""Data collector for REST API data ingestion."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

from .clients.binance_rest import BinanceRESTClient, BackfillCheckpoint
from .writers.s3_writer import S3BronzeWriter
from .config.settings import RestIngestorConfig
from .config.aws_config import AWSClientManager


logger = logging.getLogger(__name__)


class DataCollector:
    """Orchestrates data collection from Binance REST API to S3."""
    
    def __init__(self, config: RestIngestorConfig):
        self.config = config
        self.aws_client_manager = AWSClientManager(config.aws)
        self.s3_writer = S3BronzeWriter(self.aws_client_manager, config.aws)
        
        logger.info("DataCollector initialized")
    
    async def collect_agg_trades(
        self, 
        symbol: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> Dict[str, Any]:
        """Collect aggregated trades data."""
        logger.info(f"Collecting aggTrades for {symbol} from {start_time} to {end_time}")
        
        stats = {
            "data_type": "aggTrades",
            "symbol": symbol,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "records_collected": 0,
            "files_written": 0,
            "errors": 0
        }
        
        try:
            # Create REST client
            rest_client = BinanceRESTClient(
                config=self.config.binance,
                retry_config=self.config.retry
            )
            
            async with rest_client:
                # Use backfill method for resumable collection
                checkpoint = BackfillCheckpoint(
                    symbol=symbol,
                    last_timestamp=int(start_time.timestamp() * 1000)
                )
                
                batch_count = 0
                current_batch = []
                batch_size = 1000  # Process in batches
                
                async for trade in rest_client.backfill_agg_trades(
                    symbol=symbol,
                    start_time=start_time,
                    end_time=end_time,
                    checkpoint=checkpoint
                ):
                    current_batch.append(trade)
                    stats["records_collected"] += 1
                    
                    # Write batch when full
                    if len(current_batch) >= batch_size:
                        await self._write_batch_to_s3(
                            "aggTrades", symbol, current_batch, stats
                        )
                        current_batch = []
                        batch_count += 1
                        
                        # Log progress every 10 batches
                        if batch_count % 10 == 0:
                            logger.info(f"Processed {batch_count} batches for {symbol} aggTrades")
                
                # Write remaining records
                if current_batch:
                    await self._write_batch_to_s3(
                        "aggTrades", symbol, current_batch, stats
                    )
        
        except Exception as e:
            logger.error(f"Error collecting aggTrades for {symbol}: {e}", exc_info=True)
            stats["errors"] += 1
            stats["error_message"] = str(e)
        
        return stats
    
    async def collect_klines(
        self, 
        symbol: str, 
        start_time: datetime, 
        end_time: datetime,
        interval: str = "1m"
    ) -> Dict[str, Any]:
        """Collect kline/candlestick data."""
        logger.info(f"Collecting klines for {symbol} from {start_time} to {end_time}")
        
        stats = {
            "data_type": "klines",
            "symbol": symbol,
            "interval": interval,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "records_collected": 0,
            "files_written": 0,
            "errors": 0
        }
        
        try:
            rest_client = BinanceRESTClient(
                config=self.config.binance,
                retry_config=self.config.retry
            )
            
            async with rest_client:
                # Collect klines in chunks to handle large time ranges
                current_time = start_time
                
                while current_time < end_time:
                    # Binance allows max 1000 klines per request
                    # For 1m interval, this covers ~16.67 hours
                    chunk_end = min(current_time + timedelta(hours=16), end_time)
                    
                    klines = await rest_client.get_klines(
                        symbol=symbol,
                        interval=interval,
                        start_time=int(current_time.timestamp() * 1000),
                        end_time=int(chunk_end.timestamp() * 1000),
                        limit=1000
                    )
                    
                    if klines:
                        # Write klines to S3
                        success = await self.s3_writer.write_klines(
                            symbol=symbol,
                            klines=klines,
                            interval=interval,
                            timestamp=current_time
                        )
                        
                        if success:
                            stats["records_collected"] += len(klines)
                            stats["files_written"] += 1
                        else:
                            stats["errors"] += 1
                    
                    current_time = chunk_end
                    
                    # Small delay to respect rate limits
                    await asyncio.sleep(0.1)
        
        except Exception as e:
            logger.error(f"Error collecting klines for {symbol}: {e}", exc_info=True)
            stats["errors"] += 1
            stats["error_message"] = str(e)
        
        return stats
    
    async def collect_depth_snapshots(
        self, 
        symbol: str, 
        start_time: datetime, 
        end_time: datetime
    ) -> Dict[str, Any]:
        """Collect order book depth snapshots."""
        logger.info(f"Collecting depth snapshots for {symbol}")
        
        stats = {
            "data_type": "depth",
            "symbol": symbol,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "records_collected": 0,
            "files_written": 0,
            "errors": 0
        }
        
        try:
            rest_client = BinanceRESTClient(
                config=self.config.binance,
                retry_config=self.config.retry
            )
            
            async with rest_client:
                # Take snapshots at regular intervals
                snapshot_interval = timedelta(minutes=5)  # Every 5 minutes
                current_time = start_time
                
                while current_time < end_time:
                    depth_data = await rest_client.get_depth_snapshot(
                        symbol=symbol,
                        limit=100  # Top 100 levels
                    )
                    
                    if depth_data:
                        success = await self.s3_writer.write_depth_snapshot(
                            symbol=symbol,
                            depth_data=depth_data,
                            timestamp=current_time
                        )
                        
                        if success:
                            stats["records_collected"] += 1
                            stats["files_written"] += 1
                        else:
                            stats["errors"] += 1
                    
                    current_time += snapshot_interval
                    
                    # Delay between snapshots
                    await asyncio.sleep(1)
        
        except Exception as e:
            logger.error(f"Error collecting depth snapshots for {symbol}: {e}", exc_info=True)
            stats["errors"] += 1
            stats["error_message"] = str(e)
        
        return stats
    
    async def _write_batch_to_s3(
        self, 
        data_type: str, 
        symbol: str, 
        batch: List[Dict[str, Any]], 
        stats: Dict[str, Any]
    ):
        """Write a batch of records to S3."""
        try:
            if data_type == "aggTrades":
                success = await self.s3_writer.write_agg_trades(
                    symbol=symbol,
                    trades=batch
                )
            else:
                logger.warning(f"Unknown data type for batch write: {data_type}")
                return
            
            if success:
                stats["files_written"] += 1
            else:
                stats["errors"] += 1
                
        except Exception as e:
            logger.error(f"Failed to write batch to S3: {e}", exc_info=True)
            stats["errors"] += 1
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the data collector."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        try:
            # Check S3 writer health
            s3_health = await self.s3_writer.health_check()
            health_status["components"]["s3_writer"] = s3_health
            
            if s3_health.get("status") != "healthy":
                health_status["status"] = "degraded"
                
        except Exception as e:
            health_status["components"]["s3_writer"] = {
                "status": "unhealthy", 
                "error": str(e)
            }
            health_status["status"] = "unhealthy"
        
        return health_status