"""SBE Ingestor Service - Real-time SBE data streaming to Kinesis."""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from .stream_processor import SBEStreamProcessor
from .config.settings import load_config
from .utils.logging import setup_logging


logger = logging.getLogger(__name__)


class SBEIngestorService:
    """Main SBE ingestor service for real-time data streaming."""
    
    def __init__(self, config_file: str = "config/local.yaml"):
        self.config = load_config(config_file)
        self.stream_processor: Optional[SBEStreamProcessor] = None
        self._shutdown_event = asyncio.Event()
        
        # Setup logging
        setup_logging(self.config.logging)
        logger.info("SBE Ingestor Service initialized")
    
    async def start(self):
        """Start the SBE ingestor service."""
        logger.info("Starting SBE Ingestor Service")
        
        # Initialize stream processor
        self.stream_processor = SBEStreamProcessor(self.config)
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Start stream processing
        processor_task = asyncio.create_task(self.stream_processor.start())
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        # Graceful shutdown
        logger.info("Shutting down SBE Ingestor Service")
        if self.stream_processor:
            await self.stream_processor.stop()
        
        processor_task.cancel()
        try:
            await processor_task
        except asyncio.CancelledError:
            pass
        
        logger.info("SBE Ingestor Service stopped")
    
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
            "service": "sbe-ingestor",
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "components": {}
        }
        
        if self.stream_processor:
            processor_health = await self.stream_processor.health_check()
            health_status["components"]["stream_processor"] = processor_health
        
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
    service = SBEIngestorService(config_file)
    
    try:
        await service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())