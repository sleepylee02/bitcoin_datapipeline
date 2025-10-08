"""Main ingestion service orchestrating REST and SBE data flows."""

import asyncio
import logging
import signal
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum

from ..config.settings import IngestorSettings
from ..config.aws_config import AWSClientManager
from ..clients.binance_rest import BinanceRESTClient, BackfillCheckpoint
from ..clients.binance_sbe import BinanceSBEClient, SBEMessage, SBEMessageType
from ..clients.kinesis_client import KinesisProducer
from ..data.s3_writer import S3BronzeWriter
from ..utils.logging import setup_logging

logger = logging.getLogger(__name__)


class ServiceMode(Enum):
    """Service operation modes."""
    REST_ONLY = "rest"
    SBE_ONLY = "sbe"
    BOTH = "both"


@dataclass
class ServiceStats:
    """Service-level statistics."""
    start_time: float
    messages_processed: int = 0
    records_written_s3: int = 0
    records_sent_kinesis: int = 0
    errors: int = 0
    last_activity: Optional[float] = None


class IngestService:
    """
    Main ingestion service that orchestrates data flows.
    
    Supports:
    - REST mode: Historical data backfill to S3
    - SBE mode: Real-time streaming to Kinesis
    - Both modes: Combined operation
    """
    
    def __init__(self, settings: IngestorSettings):
        self.settings = settings
        self.mode = ServiceMode(settings.mode)
        
        # Initialize AWS clients
        self.aws_client_manager = AWSClientManager(settings.aws)
        
        # Initialize service components
        self.kinesis_producer: Optional[KinesisProducer] = None
        self.s3_writer: Optional[S3BronzeWriter] = None
        self.rest_client: Optional[BinanceRESTClient] = None
        self.sbe_client: Optional[BinanceSBEClient] = None
        
        # Service state
        self.running = False
        self.shutdown_event = asyncio.Event()
        self.stats = ServiceStats(start_time=time.time())
        
        # Tasks
        self.tasks: List[asyncio.Task] = []
        
        logger.info(f"IngestService initialized in {self.mode.value} mode")
    
    async def start(self):
        """Start the ingestion service."""
        if self.running:
            logger.warning("Service already running")
            return
        
        try:
            logger.info("Starting IngestService...")
            
            # Setup signal handlers
            self._setup_signal_handlers()
            
            # Initialize components
            await self._initialize_components()
            
            # Verify AWS connections
            await self._verify_aws_connections()
            
            # Start background tasks based on mode
            await self._start_mode_specific_tasks()
            
            self.running = True
            self.stats.start_time = time.time()
            
            logger.info(f"IngestService started successfully in {self.mode.value} mode")
            
            # Wait for shutdown signal
            await self.shutdown_event.wait()
            
        except Exception as e:
            logger.error(f"Failed to start IngestService: {e}")
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Stop the ingestion service gracefully."""
        if not self.running:
            return
        
        logger.info("Stopping IngestService...")
        self.running = False
        
        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()
        
        # Stop components
        await self._stop_components()
        
        logger.info("IngestService stopped")
    
    async def _initialize_components(self):
        """Initialize service components based on mode."""
        
        if self.mode in [ServiceMode.SBE_ONLY, ServiceMode.BOTH]:
            # Initialize Kinesis producer for real-time streaming
            self.kinesis_producer = KinesisProducer(
                self.aws_client_manager,
                self.settings.aws
            )
            await self.kinesis_producer.start()
            
            # Initialize SBE client
            self.sbe_client = BinanceSBEClient(self.settings.binance)
            self._register_sbe_handlers()
        
        if self.mode in [ServiceMode.REST_ONLY, ServiceMode.BOTH]:
            # Initialize S3 writer for historical data
            self.s3_writer = S3BronzeWriter(
                self.aws_client_manager,
                self.settings.aws
            )
            
            # Initialize REST client
            self.rest_client = BinanceRESTClient(
                self.settings.binance,
                self.settings.retry
            )
    
    async def _verify_aws_connections(self):
        """Verify AWS service connections."""
        logger.info("Verifying AWS connections...")
        
        connection_status = self.aws_client_manager.verify_connections()
        
        for service, status in connection_status.items():
            if status == 'healthy':
                logger.info(f"✓ {service.upper()} connection verified")
            else:
                logger.error(f"✗ {service.upper()} connection failed: {status}")
                raise RuntimeError(f"AWS {service} connection failed")
        
        # Ensure required resources exist
        if self.mode in [ServiceMode.SBE_ONLY, ServiceMode.BOTH]:
            if not await self.aws_client_manager.ensure_streams_exist():
                raise RuntimeError("Required Kinesis streams not available")
        
        if self.mode in [ServiceMode.REST_ONLY, ServiceMode.BOTH]:
            if not await self.aws_client_manager.ensure_bucket_exists():
                raise RuntimeError("Required S3 bucket not available")
        
        logger.info("AWS connections verified successfully")
    
    async def _start_mode_specific_tasks(self):
        """Start tasks based on service mode."""
        
        if self.mode == ServiceMode.REST_ONLY:
            self.tasks.append(asyncio.create_task(self._run_rest_backfill()))
        
        elif self.mode == ServiceMode.SBE_ONLY:
            self.tasks.append(asyncio.create_task(self._run_sbe_streaming()))
        
        elif self.mode == ServiceMode.BOTH:
            self.tasks.append(asyncio.create_task(self._run_rest_backfill()))
            self.tasks.append(asyncio.create_task(self._run_sbe_streaming()))
        
        # Add monitoring task
        self.tasks.append(asyncio.create_task(self._monitoring_loop()))
    
    async def _run_rest_backfill(self):
        """Run REST API backfill process."""
        logger.info("Starting REST backfill process")
        
        try:
            async with self.rest_client as client:
                for symbol in self.settings.binance.symbols:
                    await self._backfill_symbol_data(client, symbol)
            
            logger.info("REST backfill completed successfully")
            
        except Exception as e:
            logger.error(f"REST backfill failed: {e}")
            self.stats.errors += 1
            raise
    
    async def _backfill_symbol_data(self, client: BinanceRESTClient, symbol: str):
        """Backfill historical data for a specific symbol."""
        logger.info(f"Starting backfill for {symbol}")
        
        # Define backfill period (last 7 days as example)
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(days=7)
        
        # Create checkpoint for resumable backfill
        checkpoint = BackfillCheckpoint(symbol=symbol, last_timestamp=0)
        
        try:
            # Backfill aggregated trades
            record_count = 0
            async for trade_data in client.backfill_agg_trades(
                symbol=symbol,
                start_time=start_time,
                end_time=end_time,
                checkpoint=checkpoint
            ):\n                # Write to S3 in batches\n                await self.s3_writer.write_buffered(f\"{symbol}_aggTrades\", trade_data)\n                record_count += 1\n                \n                if record_count % 1000 == 0:\n                    logger.debug(f\"Processed {record_count} aggTrades for {symbol}\")\n                \n                self.stats.messages_processed += 1\n                self.stats.records_written_s3 += 1\n                self.stats.last_activity = time.time()\n            \n            # Flush any remaining buffered data\n            await self.s3_writer.flush_all_buffers()\n            \n            logger.info(f\"Completed backfill for {symbol}: {record_count} records\")\n            \n        except Exception as e:\n            logger.error(f\"Backfill failed for {symbol}: {e}\")\n            self.stats.errors += 1\n            raise\n    \n    async def _run_sbe_streaming(self):\n        \"\"\"Run SBE real-time streaming process.\"\"\"\n        logger.info(\"Starting SBE streaming process\")\n        \n        try:\n            await self.sbe_client.connect()\n            \n            async for message in self.sbe_client.start_streaming():\n                await self._process_sbe_message(message)\n                \n                self.stats.messages_processed += 1\n                self.stats.last_activity = time.time()\n                \n        except Exception as e:\n            logger.error(f\"SBE streaming failed: {e}\")\n            self.stats.errors += 1\n            raise\n        finally:\n            await self.sbe_client.disconnect()\n    \n    def _register_sbe_handlers(self):\n        \"\"\"Register handlers for different SBE message types.\"\"\"\n        \n        async def handle_trade(message: SBEMessage):\n            await self.kinesis_producer.put_trade_record(message.data)\n            self.stats.records_sent_kinesis += 1\n        \n        async def handle_bba(message: SBEMessage):\n            await self.kinesis_producer.put_bba_record(message.data)\n            self.stats.records_sent_kinesis += 1\n        \n        async def handle_depth(message: SBEMessage):\n            await self.kinesis_producer.put_depth_record(message.data)\n            self.stats.records_sent_kinesis += 1\n        \n        self.sbe_client.register_handler(SBEMessageType.TRADE, handle_trade)\n        self.sbe_client.register_handler(SBEMessageType.BEST_BID_ASK, handle_bba)\n        self.sbe_client.register_handler(SBEMessageType.DEPTH, handle_depth)\n    \n    async def _process_sbe_message(self, message: SBEMessage):\n        \"\"\"Process an individual SBE message.\"\"\"\n        try:\n            # Call registered handler\n            if message.message_type in self.sbe_client._message_handlers:\n                handler = self.sbe_client._message_handlers[message.message_type]\n                await handler(message)\n            else:\n                logger.debug(f\"No handler for message type: {message.message_type}\")\n        \n        except Exception as e:\n            logger.error(f\"Failed to process SBE message: {e}\")\n            self.stats.errors += 1\n    \n    async def _monitoring_loop(self):\n        \"\"\"Background monitoring and health check loop.\"\"\"\n        logger.info(\"Starting monitoring loop\")\n        \n        while self.running:\n            try:\n                await asyncio.sleep(30)  # Monitor every 30 seconds\n                \n                # Log basic stats\n                uptime = time.time() - self.stats.start_time\n                logger.info(\n                    f\"Service stats: uptime={uptime:.0f}s, \"\n                    f\"processed={self.stats.messages_processed}, \"\n                    f\"errors={self.stats.errors}\"\n                )\n                \n                # Check component health\n                await self._check_component_health()\n                \n            except Exception as e:\n                logger.error(f\"Monitoring loop error: {e}\")\n                await asyncio.sleep(5)\n    \n    async def _check_component_health(self):\n        \"\"\"Check health of all components.\"\"\"\n        \n        health_issues = []\n        \n        # Check SBE client health\n        if self.sbe_client:\n            sbe_health = await self.sbe_client.health_check()\n            if sbe_health['status'] != 'healthy':\n                health_issues.extend([f\"SBE: {issue}\" for issue in sbe_health['issues']])\n        \n        # Check Kinesis producer health\n        if self.kinesis_producer:\n            kinesis_health = await self.kinesis_producer.health_check()\n            if kinesis_health['status'] != 'healthy':\n                health_issues.extend([f\"Kinesis: {issue}\" for issue in kinesis_health['issues']])\n        \n        # Check S3 writer health\n        if self.s3_writer:\n            s3_health = await self.s3_writer.health_check()\n            if s3_health['status'] != 'healthy':\n                health_issues.extend([f\"S3: {issue}\" for issue in s3_health['issues']])\n        \n        if health_issues:\n            logger.warning(f\"Health issues detected: {', '.join(health_issues)}\")\n    \n    async def _stop_components(self):\n        \"\"\"Stop all service components gracefully.\"\"\"\n        \n        if self.kinesis_producer:\n            await self.kinesis_producer.stop()\n        \n        if self.sbe_client:\n            await self.sbe_client.disconnect()\n        \n        if self.s3_writer:\n            await self.s3_writer.flush_all_buffers()\n    \n    def _setup_signal_handlers(self):\n        \"\"\"Setup signal handlers for graceful shutdown.\"\"\"\n        \n        def signal_handler(sig, frame):\n            logger.info(f\"Received signal {sig}, initiating shutdown...\")\n            self.shutdown_event.set()\n        \n        signal.signal(signal.SIGTERM, signal_handler)\n        signal.signal(signal.SIGINT, signal_handler)\n    \n    def get_stats(self) -> Dict[str, Any]:\n        \"\"\"Get comprehensive service statistics.\"\"\"\n        \n        uptime = time.time() - self.stats.start_time\n        \n        stats = {\n            'service': {\n                'mode': self.mode.value,\n                'uptime_seconds': uptime,\n                'running': self.running,\n                'messages_processed': self.stats.messages_processed,\n                'records_written_s3': self.stats.records_written_s3,\n                'records_sent_kinesis': self.stats.records_sent_kinesis,\n                'errors': self.stats.errors,\n                'last_activity': self.stats.last_activity\n            }\n        }\n        \n        # Add component stats\n        if self.sbe_client:\n            stats['sbe_client'] = self.sbe_client.get_stats()\n        \n        if self.kinesis_producer:\n            stats['kinesis_producer'] = self.kinesis_producer.get_stats()\n        \n        if self.s3_writer:\n            stats['s3_writer'] = self.s3_writer.get_stats()\n        \n        return stats\n    \n    async def health_check(self) -> Dict[str, Any]:\n        \"\"\"Comprehensive health check for the service.\"\"\"\n        \n        overall_health = {\n            'healthy': True,\n            'issues': []\n        }\n        \n        component_health = {}\n        \n        # Check service-level health\n        if not self.running:\n            overall_health['healthy'] = False\n            overall_health['issues'].append('Service not running')\n        \n        # Check last activity\n        if self.stats.last_activity:\n            time_since_activity = time.time() - self.stats.last_activity\n            if time_since_activity > 300:  # 5 minutes\n                overall_health['healthy'] = False\n                overall_health['issues'].append(f'No activity for {time_since_activity:.0f}s')\n        \n        # Check component health\n        if self.sbe_client:\n            component_health['sbe_client'] = await self.sbe_client.health_check()\n            if component_health['sbe_client']['status'] != 'healthy':\n                overall_health['healthy'] = False\n        \n        if self.kinesis_producer:\n            component_health['kinesis_producer'] = await self.kinesis_producer.health_check()\n            if component_health['kinesis_producer']['status'] != 'healthy':\n                overall_health['healthy'] = False\n        \n        if self.s3_writer:\n            component_health['s3_writer'] = await self.s3_writer.health_check()\n            if component_health['s3_writer']['status'] != 'healthy':\n                overall_health['healthy'] = False\n        \n        return {\n            'status': 'healthy' if overall_health['healthy'] else 'unhealthy',\n            'overall': overall_health,\n            'components': component_health,\n            'stats': self.get_stats()\n        }"