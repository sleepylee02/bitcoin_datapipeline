"""ETL orchestrator for S3 to PostgreSQL data pipeline."""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import json

from .s3_reader import S3Reader
from .transformer import DataTransformer
from .db_writer import DatabaseWriter
from .config.settings import DataConnectorConfig


logger = logging.getLogger(__name__)


class ETLOrchestrator:
    """Orchestrates ETL process from S3 to PostgreSQL."""
    
    def __init__(self, config: DataConnectorConfig):
        self.config = config
        
        # Initialize components
        self.s3_reader = S3Reader(config)
        self.transformer = DataTransformer(config)
        self.db_writer = DatabaseWriter(config)
        
        # ETL state
        self._running = False
        self._last_processed_time = None
        
        # Statistics
        self.stats = {
            "files_processed": 0,
            "records_processed": 0,
            "records_written": 0,
            "errors": 0,
            "last_run_time": None,
            "start_time": datetime.now()
        }
        
        logger.info("ETLOrchestrator initialized")
    
    async def start(self):
        """Start the ETL process."""
        self._running = True
        logger.info("Starting ETL orchestrator")
        
        try:
            # Initialize database connection
            await self.db_writer.initialize()
            
            # Main ETL loop
            while self._running:
                try:
                    # Run ETL cycle
                    cycle_stats = await self._run_etl_cycle()
                    
                    # Update statistics
                    self._update_stats(cycle_stats)
                    
                    # Log cycle completion
                    logger.info(f"ETL cycle completed: {cycle_stats}")
                    
                    # Wait for next cycle
                    await self._wait_for_next_cycle()
                    
                except Exception as e:
                    logger.error(f"ETL cycle error: {e}", exc_info=True)
                    self.stats["errors"] += 1
                    
                    # Wait before retrying
                    await asyncio.sleep(60)
        
        except Exception as e:
            logger.error(f"ETL orchestrator error: {e}", exc_info=True)
            raise
        finally:
            await self._cleanup()
    
    async def stop(self):
        """Stop the ETL orchestrator gracefully."""
        logger.info("Stopping ETL orchestrator")
        self._running = False
        
        # Close database connections
        if self.db_writer:
            await self.db_writer.close()
        
        logger.info("ETL orchestrator stopped")
    
    async def _run_etl_cycle(self) -> Dict[str, Any]:
        """Run a single ETL cycle."""
        cycle_stats = {
            "start_time": datetime.now().isoformat(),
            "files_discovered": 0,
            "files_processed": 0,
            "records_processed": 0,
            "records_written": 0,
            "errors": 0,
            "duration_seconds": 0
        }
        
        cycle_start = datetime.now()
        
        try:
            # Discover new S3 files to process
            files_to_process = await self.s3_reader.discover_new_files(
                last_processed_time=self._last_processed_time
            )
            
            cycle_stats["files_discovered"] = len(files_to_process)
            
            if not files_to_process:
                logger.info("No new files to process")
                return cycle_stats
            
            logger.info(f"Found {len(files_to_process)} files to process")
            
            # Process files in batches
            batch_size = self.config.etl.batch_size
            
            for i in range(0, len(files_to_process), batch_size):
                batch = files_to_process[i:i + batch_size]
                batch_stats = await self._process_file_batch(batch)
                
                # Accumulate stats
                cycle_stats["files_processed"] += batch_stats["files_processed"]
                cycle_stats["records_processed"] += batch_stats["records_processed"]
                cycle_stats["records_written"] += batch_stats["records_written"]
                cycle_stats["errors"] += batch_stats["errors"]
                
                # Small delay between batches
                await asyncio.sleep(1)
            
            # Update last processed time
            if files_to_process:
                latest_file_time = max(
                    file_info["last_modified"] for file_info in files_to_process
                )
                self._last_processed_time = latest_file_time
        
        except Exception as e:
            logger.error(f"ETL cycle error: {e}", exc_info=True)
            cycle_stats["errors"] += 1
            raise
        finally:
            cycle_end = datetime.now()
            cycle_stats["duration_seconds"] = (cycle_end - cycle_start).total_seconds()
            cycle_stats["end_time"] = cycle_end.isoformat()
        
        return cycle_stats
    
    async def _process_file_batch(self, file_batch: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Process a batch of S3 files."""
        batch_stats = {
            "files_processed": 0,
            "records_processed": 0,
            "records_written": 0,
            "errors": 0
        }
        
        for file_info in file_batch:
            try:
                # Read data from S3
                raw_data = await self.s3_reader.read_file(file_info)
                
                if not raw_data:
                    logger.warning(f"No data in file: {file_info['key']}")
                    continue
                
                # Transform data
                transformed_data = await self.transformer.transform(raw_data, file_info)
                
                if not transformed_data:
                    logger.warning(f"No transformed data for file: {file_info['key']}")
                    continue
                
                # Write to database
                records_written = await self.db_writer.write_batch(transformed_data)
                
                # Update statistics
                batch_stats["files_processed"] += 1
                batch_stats["records_processed"] += len(raw_data)
                batch_stats["records_written"] += records_written
                
                logger.debug(f"Processed file {file_info['key']}: {len(raw_data)} records")
                
            except Exception as e:
                logger.error(f"Error processing file {file_info['key']}: {e}", exc_info=True)
                batch_stats["errors"] += 1
        
        return batch_stats
    
    async def _wait_for_next_cycle(self):
        """Wait for the next ETL cycle."""
        interval_seconds = self.config.etl.cycle_interval_seconds
        logger.debug(f"Waiting {interval_seconds} seconds for next ETL cycle")
        
        # Use shorter sleep intervals to allow for responsive shutdown
        sleep_interval = min(60, interval_seconds)
        total_waited = 0
        
        while total_waited < interval_seconds and self._running:
            remaining = interval_seconds - total_waited
            current_sleep = min(sleep_interval, remaining)
            
            await asyncio.sleep(current_sleep)
            total_waited += current_sleep
    
    def _update_stats(self, cycle_stats: Dict[str, Any]):
        """Update overall statistics with cycle results."""
        self.stats["files_processed"] += cycle_stats["files_processed"]
        self.stats["records_processed"] += cycle_stats["records_processed"]
        self.stats["records_written"] += cycle_stats["records_written"]
        self.stats["errors"] += cycle_stats["errors"]
        self.stats["last_run_time"] = cycle_stats["start_time"]
    
    async def _cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up ETL orchestrator resources")
        
        # Close database connection
        if self.db_writer:
            await self.db_writer.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the ETL orchestrator."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "running": self._running,
            "stats": self.stats.copy(),
            "components": {}
        }
        
        # Check S3 reader health
        try:
            s3_health = await self.s3_reader.health_check()
            health_status["components"]["s3_reader"] = s3_health
            
            if s3_health.get("status") != "healthy":
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["components"]["s3_reader"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "unhealthy"
        
        # Check database writer health
        try:
            db_health = await self.db_writer.health_check()
            health_status["components"]["db_writer"] = db_health
            
            if db_health.get("status") != "healthy":
                health_status["status"] = "unhealthy"
        except Exception as e:
            health_status["components"]["db_writer"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "unhealthy"
        
        # Check for stale processing
        if self.stats["last_run_time"]:
            last_run = datetime.fromisoformat(self.stats["last_run_time"])
            time_since_last = (datetime.now() - last_run).total_seconds()
            
            # If no processing for longer than 2 cycles, mark as degraded
            max_idle_time = self.config.etl.cycle_interval_seconds * 2
            if time_since_last > max_idle_time:
                health_status["status"] = "degraded"
                health_status["warning"] = f"No processing for {time_since_last:.0f} seconds"
        
        # Check error rate
        total_processed = self.stats["records_processed"]
        if total_processed > 0:
            error_rate = self.stats["errors"] / max(self.stats["files_processed"], 1)
            if error_rate > 0.1:  # >10% file error rate
                health_status["status"] = "degraded"
                health_status["warning"] = f"High error rate: {error_rate:.2%}"
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get ETL statistics."""
        uptime = (datetime.now() - self.stats["start_time"]).total_seconds()
        
        stats = self.stats.copy()
        stats.update({
            "uptime_seconds": uptime,
            "files_per_hour": self.stats["files_processed"] / max(uptime / 3600, 1),
            "records_per_second": self.stats["records_processed"] / max(uptime, 1),
            "last_processed_time": self._last_processed_time.isoformat() if self._last_processed_time else None
        })
        
        return stats