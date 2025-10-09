"""Data Connector Service - S3 to RDS PostgreSQL ETL."""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from .etl_orchestrator import ETLOrchestrator
from .config.settings import load_config
from .utils.logging import setup_logging


logger = logging.getLogger(__name__)


class DataConnectorService:
    """Main data connector service for S3 to PostgreSQL ETL."""
    
    def __init__(self, config_file: str = "config/local.yaml"):
        self.config = load_config(config_file)
        self.etl_orchestrator: Optional[ETLOrchestrator] = None
        self._shutdown_event = asyncio.Event()
        
        # Setup logging
        setup_logging(self.config.logging)
        logger.info("Data Connector Service initialized")
    
    async def start(self):
        """Start the data connector service."""
        logger.info("Starting Data Connector Service")
        
        # Initialize ETL orchestrator
        self.etl_orchestrator = ETLOrchestrator(self.config)
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Start ETL processing
        etl_task = asyncio.create_task(self.etl_orchestrator.start())
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        # Graceful shutdown
        logger.info("Shutting down Data Connector Service")
        if self.etl_orchestrator:
            await self.etl_orchestrator.stop()
        
        etl_task.cancel()
        try:
            await etl_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Data Connector Service stopped")
    
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
            "service": "data-connector",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {}
        }
        
        if self.etl_orchestrator:
            etl_health = await self.etl_orchestrator.health_check()
            health_status["components"]["etl_orchestrator"] = etl_health
        
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
    service = DataConnectorService(config_file)
    
    try:
        await service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())