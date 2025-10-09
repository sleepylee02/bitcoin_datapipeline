"""Stream processor for SBE data to Kinesis."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import json
import time

from .clients.binance_sbe import BinanceSBEClient
from .clients.kinesis_client import KinesisProducer
from .config.settings import SBEIngestorConfig
from .config.aws_config import AWSClientManager


logger = logging.getLogger(__name__)


class SBEStreamProcessor:
    """Processes SBE streams and publishes to Kinesis."""
    
    def __init__(self, config: SBEIngestorConfig):
        self.config = config
        self.aws_client_manager = AWSClientManager(config.aws)
        
        # Initialize clients
        self.sbe_client: Optional[BinanceSBEClient] = None
        self.kinesis_producers: Dict[str, KinesisProducer] = {}
        
        # Statistics
        self.stats = {
            "messages_processed": 0,
            "messages_sent": 0,
            "errors": 0,
            "last_message_time": None,
            "start_time": datetime.utcnow()
        }
        
        self._running = False
        logger.info("SBEStreamProcessor initialized")
    
    async def start(self):
        """Start the stream processor."""
        self._running = True
        logger.info("Starting SBE stream processor")
        
        try:
            # Initialize Kinesis producers
            await self._init_kinesis_producers()
            
            # Initialize SBE client
            self.sbe_client = BinanceSBEClient(
                config=self.config.binance,
                retry_config=self.config.retry
            )
            
            # Start message processing
            await self.sbe_client.connect()
            
            # Subscribe to streams
            for symbol in self.config.binance.symbols:
                for stream_type in self.config.binance.stream_types:
                    await self.sbe_client.subscribe(symbol, stream_type)
            
            # Process messages
            async for message in self.sbe_client.get_messages():
                if not self._running:
                    break
                
                await self._process_message(message)
            
        except Exception as e:
            logger.error(f"Stream processor error: {e}", exc_info=True)
            raise
        finally:
            await self._cleanup()
    
    async def stop(self):
        """Stop the stream processor gracefully."""
        logger.info("Stopping SBE stream processor")
        self._running = False
        
        # Close SBE client
        if self.sbe_client:
            await self.sbe_client.close()
        
        # Close Kinesis producers
        for producer in self.kinesis_producers.values():
            await producer.close()
        
        logger.info("SBE stream processor stopped")
    
    async def _init_kinesis_producers(self):
        """Initialize Kinesis producers for each stream type."""
        for stream_name, stream_config in self.config.kinesis.streams.items():
            producer = KinesisProducer(
                stream_name=stream_config,
                aws_client_manager=self.aws_client_manager,
                batch_size=self.config.kinesis.batch_size,
                flush_interval=self.config.kinesis.flush_interval_seconds
            )
            
            await producer.start()
            self.kinesis_producers[stream_name] = producer
            logger.info(f"Initialized Kinesis producer for {stream_name}")
    
    async def _process_message(self, message: Dict[str, Any]):
        """Process a single SBE message."""
        try:
            message_type = message.get("type")
            symbol = message.get("symbol")
            
            if not message_type or not symbol:
                logger.warning(f"Invalid message format: {message}")
                self.stats["errors"] += 1
                return
            
            # Enhance message with metadata
            enhanced_message = {
                **message,
                "ingest_ts": int(time.time() * 1000),
                "source": "sbe"
            }
            
            # Route to appropriate Kinesis stream
            stream_key = self._get_stream_key(message_type)
            if stream_key and stream_key in self.kinesis_producers:
                producer = self.kinesis_producers[stream_key]
                
                # Create partition key for even distribution
                partition_key = f"{symbol}_{message_type}"
                
                # Send to Kinesis
                await producer.put_record(
                    data=enhanced_message,
                    partition_key=partition_key
                )
                
                self.stats["messages_sent"] += 1
            else:
                logger.warning(f"No producer found for message type: {message_type}")
                self.stats["errors"] += 1
            
            # Update statistics
            self.stats["messages_processed"] += 1
            self.stats["last_message_time"] = datetime.utcnow()
            
            # Log progress periodically
            if self.stats["messages_processed"] % 1000 == 0:
                logger.info(f"Processed {self.stats['messages_processed']} messages")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            self.stats["errors"] += 1
    
    def _get_stream_key(self, message_type: str) -> Optional[str]:
        """Map message type to Kinesis stream key."""
        mapping = {
            "trade": "trade",
            "bestBidAsk": "bestbidask",
            "depth": "depth"
        }
        return mapping.get(message_type)
    
    async def _cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up SBE stream processor resources")
        
        # Flush any remaining messages
        for producer in self.kinesis_producers.values():
            try:
                await producer.flush()
            except Exception as e:
                logger.error(f"Error flushing producer: {e}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the stream processor."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "running": self._running,
            "stats": self.stats.copy(),
            "components": {}
        }
        
        # Check SBE client health
        if self.sbe_client:
            try:
                sbe_health = await self.sbe_client.health_check()
                health_status["components"]["sbe_client"] = sbe_health
                
                if sbe_health.get("status") != "healthy":
                    health_status["status"] = "degraded"
            except Exception as e:
                health_status["components"]["sbe_client"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_status["status"] = "unhealthy"
        
        # Check Kinesis producers health
        kinesis_health = {}
        for stream_name, producer in self.kinesis_producers.items():
            try:
                producer_health = await producer.health_check()
                kinesis_health[stream_name] = producer_health
                
                if producer_health.get("status") != "healthy":
                    health_status["status"] = "degraded"
            except Exception as e:
                kinesis_health[stream_name] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
                health_status["status"] = "unhealthy"
        
        health_status["components"]["kinesis_producers"] = kinesis_health
        
        # Check message freshness
        if self.stats["last_message_time"]:
            time_since_last = (
                datetime.utcnow() - self.stats["last_message_time"]
            ).total_seconds()
            
            if time_since_last > 60:  # No messages for 1 minute
                health_status["status"] = "degraded"
                health_status["warning"] = f"No messages for {time_since_last:.0f} seconds"
        
        # Calculate error rate
        total_processed = self.stats["messages_processed"]
        if total_processed > 0:
            error_rate = self.stats["errors"] / total_processed
            if error_rate > 0.05:  # >5% error rate
                health_status["status"] = "degraded"
                health_status["warning"] = f"High error rate: {error_rate:.2%}"
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get processor statistics."""
        uptime = (datetime.utcnow() - self.stats["start_time"]).total_seconds()
        
        stats = self.stats.copy()
        stats.update({
            "uptime_seconds": uptime,
            "messages_per_second": self.stats["messages_processed"] / max(uptime, 1),
            "error_rate": self.stats["errors"] / max(self.stats["messages_processed"], 1)
        })
        
        return stats