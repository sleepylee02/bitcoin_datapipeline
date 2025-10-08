"""REST Ingestor Service - Periodic historical data collection to S3."""

import asyncio
import logging
import signal
import sys
from datetime import datetime, timedelta
from typing import Optional

from .scheduler import RestScheduler
from .config.settings import load_config
from .utils.logging import setup_logging


logger = logging.getLogger(__name__)


class RestIngestorService:
    """Main REST ingestor service for periodic data collection."""
    
    def __init__(self, config_file: str = "config/local.yaml"):
        self.config = load_config(config_file)
        self.scheduler: Optional[RestScheduler] = None
        self._shutdown_event = asyncio.Event()
        
        # Setup logging
        setup_logging(self.config.logging)
        logger.info("REST Ingestor Service initialized")
    
    async def start(self):
        """Start the REST ingestor service."""
        logger.info("Starting REST Ingestor Service")
        
        # Initialize scheduler
        self.scheduler = RestScheduler(self.config)
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Start scheduler
        scheduler_task = asyncio.create_task(self.scheduler.start())
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        # Graceful shutdown
        logger.info("Shutting down REST Ingestor Service")
        if self.scheduler:
            await self.scheduler.stop()
        
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass
        
        logger.info("REST Ingestor Service stopped")
    
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown."""
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, initiating shutdown")
            self._shutdown_event.set()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
    
    async def health_check(self) -> dict:
        """Perform health check."""
        health_status = {
            "service": "rest-ingestor",
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        if self.scheduler:
            scheduler_health = await self.scheduler.health_check()
            health_status["components"]["scheduler"] = scheduler_health
        
        # Determine overall health
        component_statuses = [
            comp.get("status", "unknown") 
            for comp in health_status["components"].values()
        ]
        
        if any(status == "unhealthy" for status in component_statuses):
            health_status["status"] = "unhealthy"
        elif any(status == "degraded" for status in component_statuses):
            health_status["status"] = "degraded"
        
        return health_status


async def main():
    """Main entry point."""
    import os
    
    config_file = os.getenv("CONFIG_FILE", "config/local.yaml")
    service = RestIngestorService(config_file)
    
    try:
        await service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())