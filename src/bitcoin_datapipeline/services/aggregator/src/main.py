"""Aggregator Service - Kinesis to Redis feature aggregation."""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Optional

from .stream_aggregator import StreamAggregator
from .config.settings import load_config
from .utils.logging import setup_logging


logger = logging.getLogger(__name__)


class AggregatorService:
    """Main aggregator service for Kinesis to Redis feature aggregation."""
    
    def __init__(self, config_file: str = "config/local.yaml"):
        self.config = load_config(config_file)
        self.stream_aggregator: Optional[StreamAggregator] = None
        self._shutdown_event = asyncio.Event()
        
        # Setup logging
        setup_logging(self.config.logging)
        logger.info("Aggregator Service initialized")
    
    async def start(self):
        """Start the aggregator service."""
        logger.info("Starting Aggregator Service")
        
        # Initialize stream aggregator
        self.stream_aggregator = StreamAggregator(self.config)
        
        # Setup signal handlers
        self._setup_signal_handlers()
        
        # Start stream aggregation
        aggregator_task = asyncio.create_task(self.stream_aggregator.start())
        
        # Wait for shutdown signal
        await self._shutdown_event.wait()
        
        # Graceful shutdown
        logger.info("Shutting down Aggregator Service")
        if self.stream_aggregator:
            await self.stream_aggregator.stop()
        
        aggregator_task.cancel()
        try:
            await aggregator_task
        except asyncio.CancelledError:
            pass
        
        logger.info("Aggregator Service stopped")
    
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
            "service": "aggregator",
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "components": {}
        }
        
        if self.stream_aggregator:
            aggregator_health = await self.stream_aggregator.health_check()
            health_status["components"]["stream_aggregator"] = aggregator_health
        
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
    service = AggregatorService(config_file)
    
    try:
        await service.start()
    except Exception as e:
        logger.error(f"Service failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())