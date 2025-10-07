"""Scheduler for periodic REST data collection."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import json

from .collector import DataCollector
from .checkpoint import CheckpointManager
from .config.settings import RestIngestorConfig


logger = logging.getLogger(__name__)


class RestScheduler:
    """Scheduler for periodic data collection from Binance REST API."""
    
    def __init__(self, config: RestIngestorConfig):
        self.config = config
        self.collector = DataCollector(config)
        self.checkpoint_manager = CheckpointManager(config)
        self._running = False
        self._tasks = []
        
        logger.info(f"Scheduler initialized with interval: {config.scheduler.collection_interval}")
    
    async def start(self):
        """Start the periodic collection scheduler."""
        self._running = True
        logger.info("Starting REST data collection scheduler")
        
        # Start collection tasks for each symbol
        for symbol in self.config.binance.symbols:
            task = asyncio.create_task(self._collection_loop(symbol))
            self._tasks.append(task)
        
        # Wait for all tasks to complete
        try:
            await asyncio.gather(*self._tasks)
        except Exception as e:
            logger.error(f"Scheduler error: {e}", exc_info=True)
            raise
    
    async def stop(self):
        """Stop the scheduler gracefully."""
        logger.info("Stopping REST data collection scheduler")
        self._running = False
        
        # Cancel all running tasks
        for task in self._tasks:
            task.cancel()
        
        # Wait for tasks to finish cancellation
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        self._tasks.clear()
        logger.info("Scheduler stopped")
    
    async def _collection_loop(self, symbol: str):
        """Main collection loop for a specific symbol."""
        logger.info(f"Starting collection loop for {symbol}")
        
        while self._running:
            try:
                # Calculate collection window
                end_time = datetime.utcnow()
                
                # Get last checkpoint
                checkpoint = await self.checkpoint_manager.get_checkpoint(symbol)
                
                if checkpoint:
                    start_time = datetime.fromtimestamp(checkpoint.last_timestamp / 1000)
                    # Add overlap to prevent gaps
                    start_time -= timedelta(minutes=self.config.scheduler.overlap_minutes)
                else:
                    # Default to collect last interval
                    start_time = end_time - self._parse_interval(self.config.scheduler.collection_interval)
                
                logger.info(f"Collecting {symbol} data from {start_time} to {end_time}")
                
                # Collect data for each configured data type
                collection_stats = {}
                
                for data_type in self.config.scheduler.data_types:
                    try:
                        if data_type == "aggTrades":
                            stats = await self.collector.collect_agg_trades(symbol, start_time, end_time)
                        elif data_type == "klines":
                            stats = await self.collector.collect_klines(symbol, start_time, end_time)
                        elif data_type == "depth":
                            stats = await self.collector.collect_depth_snapshots(symbol, start_time, end_time)
                        else:
                            logger.warning(f"Unknown data type: {data_type}")
                            continue
                        
                        collection_stats[data_type] = stats
                        logger.info(f"Collected {symbol} {data_type}: {stats}")
                        
                    except Exception as e:
                        logger.error(f"Failed to collect {symbol} {data_type}: {e}", exc_info=True)
                        collection_stats[data_type] = {"error": str(e)}
                
                # Update checkpoint on successful collection
                if any(stats.get("records_collected", 0) > 0 for stats in collection_stats.values()):
                    await self.checkpoint_manager.save_checkpoint(
                        symbol, 
                        int(end_time.timestamp() * 1000),
                        collection_stats
                    )
                
                # Log collection summary
                total_records = sum(
                    stats.get("records_collected", 0) 
                    for stats in collection_stats.values()
                )
                logger.info(f"Collection cycle completed for {symbol}: {total_records} total records")
                
                # Wait for next collection interval
                await self._wait_for_next_collection()
                
            except Exception as e:
                logger.error(f"Collection loop error for {symbol}: {e}", exc_info=True)
                # Wait before retrying
                await asyncio.sleep(60)
        
        logger.info(f"Collection loop stopped for {symbol}")
    
    async def _wait_for_next_collection(self):
        """Wait for the next collection interval."""
        interval_seconds = self._interval_to_seconds(self.config.scheduler.collection_interval)
        logger.debug(f"Waiting {interval_seconds} seconds for next collection")
        
        # Use shorter sleep intervals to allow for responsive shutdown
        sleep_interval = min(60, interval_seconds)  # Sleep in 1-minute chunks max
        total_waited = 0
        
        while total_waited < interval_seconds and self._running:
            remaining = interval_seconds - total_waited
            current_sleep = min(sleep_interval, remaining)
            
            await asyncio.sleep(current_sleep)
            total_waited += current_sleep
    
    def _parse_interval(self, interval_str: str) -> timedelta:
        """Parse interval string (e.g., '1h', '6h', '1d') to timedelta."""
        interval_str = interval_str.lower().strip()
        
        if interval_str.endswith('h'):
            hours = int(interval_str[:-1])
            return timedelta(hours=hours)
        elif interval_str.endswith('d'):
            days = int(interval_str[:-1])
            return timedelta(days=days)
        elif interval_str.endswith('m'):
            minutes = int(interval_str[:-1])
            return timedelta(minutes=minutes)
        else:
            raise ValueError(f"Invalid interval format: {interval_str}")
    
    def _interval_to_seconds(self, interval_str: str) -> int:
        """Convert interval string to seconds."""
        delta = self._parse_interval(interval_str)
        return int(delta.total_seconds())
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the scheduler."""
        health_status = {
            "status": "healthy" if self._running else "stopped",
            "running_tasks": len(self._tasks),
            "symbols": self.config.binance.symbols,
            "collection_interval": self.config.scheduler.collection_interval,
            "last_check": datetime.utcnow().isoformat()
        }
        
        # Check collector health
        try:
            collector_health = await self.collector.health_check()
            health_status["collector"] = collector_health
            
            if collector_health.get("status") != "healthy":
                health_status["status"] = "degraded"
                
        except Exception as e:
            health_status["collector"] = {"status": "unhealthy", "error": str(e)}
            health_status["status"] = "unhealthy"
        
        return health_status