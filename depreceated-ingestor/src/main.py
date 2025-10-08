"""Main entry point for the Bitcoin Ingestor Service."""

import asyncio
import sys
import os
from pathlib import Path

# Add the src directory to the Python path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import load_settings
from services.ingest_service import IngestService
from services.health_service import HealthService
from services.metrics_service import MetricsService
from utils.logging import setup_logging


async def main():
    """Main entry point for the ingestor service."""
    
    # Load configuration
    # Priority: 1) CONFIG_FILE env var, 2) default based on environment, 3) env vars only
    config_file = os.getenv('CONFIG_FILE')
    if not config_file:
        # Default config based on environment
        env = os.getenv('ENVIRONMENT', 'local')
        config_file = f'config/{env}.yaml'
    
    settings = load_settings(config_file)
    
    # Setup logging
    setup_logging(settings.logging, settings.service_name)
    
    import logging
    logger = logging.getLogger(__name__)
    
    logger.info(f"Loaded configuration from: {config_file}")
    logger.info(f"Starting {settings.service_name} in {settings.environment} environment")
    logger.info(f"Mode: {settings.mode}")
    logger.info(f"Symbols: {settings.binance.symbols}")
    
    # Initialize services
    ingest_service = IngestService(settings)
    health_service = HealthService(settings.health, ingest_service)
    metrics_service = MetricsService(settings.metrics, ingest_service)
    
    try:
        # Start health and metrics services
        await health_service.start()
        await metrics_service.start()
        
        logger.info("Health and metrics services started")
        
        # Start main ingestion service (this will block until shutdown)
        await ingest_service.start()
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Cleanup
        await ingest_service.stop()
        await health_service.stop()
        await metrics_service.stop()
        
        logger.info("Service shutdown complete")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)
