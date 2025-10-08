"""Stream aggregator for Kinesis to Redis feature pipeline."""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
import json
import time
from collections import defaultdict, deque

from .kinesis_consumer import KinesisConsumer
from .feature_builder import FeatureBuilder
from .redis_writer import RedisWriter
from .config.settings import AggregatorConfig


logger = logging.getLogger(__name__)


class StreamAggregator:
    """Aggregates real-time streams and writes features to Redis."""
    
    def __init__(self, config: AggregatorConfig):
        self.config = config
        
        # Initialize components
        self.kinesis_consumer = KinesisConsumer(config)
        self.feature_builder = FeatureBuilder(config)
        self.redis_writer = RedisWriter(config)
        
        # Aggregation state
        self._running = False
        self._message_buffers = defaultdict(lambda: deque(maxlen=1000))
        self._last_aggregation_time = defaultdict(lambda: time.time())
        
        # Statistics
        self.stats = {
            "messages_consumed": 0,
            "features_computed": 0,
            "features_written": 0,
            "errors": 0,
            "last_message_time": None,
            "start_time": datetime.now()
        }
        
        logger.info("StreamAggregator initialized")
    
    async def start(self):
        """Start the stream aggregator."""
        self._running = True
        logger.info("Starting stream aggregator")
        
        try:
            # Initialize Redis connection
            await self.redis_writer.initialize()
            
            # Start Kinesis consumer
            await self.kinesis_consumer.start()
            
            # Start aggregation loop
            aggregation_task = asyncio.create_task(self._aggregation_loop())
            
            # Start message consumption
            async for message in self.kinesis_consumer.consume_messages():
                if not self._running:
                    break
                
                await self._process_message(message)
            
            # Wait for aggregation task to complete
            aggregation_task.cancel()
            try:
                await aggregation_task
            except asyncio.CancelledError:
                pass
        
        except Exception as e:
            logger.error(f"Stream aggregator error: {e}", exc_info=True)
            raise
        finally:
            await self._cleanup()
    
    async def stop(self):
        """Stop the stream aggregator gracefully."""
        logger.info("Stopping stream aggregator")
        self._running = False
        
        # Flush remaining features
        await self._flush_all_features()
        
        # Stop components
        if self.kinesis_consumer:
            await self.kinesis_consumer.stop()
        
        if self.redis_writer:
            await self.redis_writer.close()
        
        logger.info("Stream aggregator stopped")
    
    async def _process_message(self, message: Dict[str, Any]):
        """Process a single message from Kinesis."""
        try:
            # Extract message metadata
            stream_name = message.get("stream_name")
            data = message.get("data", {})
            
            if not data:
                logger.warning(f"Empty message data from stream {stream_name}")
                self.stats["errors"] += 1
                return
            
            # Determine message type and symbol
            message_type = data.get("type", "unknown")
            symbol = data.get("symbol")
            
            if not symbol:
                logger.warning(f"Message missing symbol: {data}")
                self.stats["errors"] += 1
                return
            
            # Add to appropriate buffer
            buffer_key = f"{symbol}_{message_type}"
            self._message_buffers[buffer_key].append({
                "timestamp": time.time(),
                "data": data,
                "stream_name": stream_name,
                "message_type": message_type
            })
            
            # Update statistics
            self.stats["messages_consumed"] += 1
            self.stats["last_message_time"] = datetime.now()
            
            # Log progress periodically
            if self.stats["messages_consumed"] % 1000 == 0:
                logger.info(f"Processed {self.stats['messages_consumed']} messages")
        
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            self.stats["errors"] += 1
    
    async def _aggregation_loop(self):
        """Main aggregation loop that runs periodically."""
        while self._running:
            try:
                current_time = time.time()
                
                # Check each buffer for aggregation
                for buffer_key, buffer in self._message_buffers.items():
                    if not buffer:
                        continue
                    
                    last_agg_time = self._last_aggregation_time[buffer_key]
                    time_since_last = current_time - last_agg_time
                    
                    # Trigger aggregation if conditions are met
                    should_aggregate = (
                        len(buffer) >= self.config.aggregation.min_messages or
                        time_since_last >= self.config.aggregation.max_interval_seconds
                    )
                    
                    if should_aggregate:
                        await self._aggregate_buffer(buffer_key, buffer)
                        self._last_aggregation_time[buffer_key] = current_time
                
                # Sleep for aggregation interval
                await asyncio.sleep(self.config.aggregation.check_interval_seconds)
            
            except Exception as e:
                logger.error(f"Aggregation loop error: {e}", exc_info=True)
                await asyncio.sleep(5)  # Brief pause on error
    
    async def _aggregate_buffer(self, buffer_key: str, buffer: deque):
        """Aggregate messages in a buffer and write features to Redis."""
        if not buffer:
            return
        
        try:
            # Extract symbol and message type from buffer key
            symbol, message_type = buffer_key.split('_', 1)
            
            # Get messages to aggregate
            messages_to_aggregate = list(buffer)
            buffer.clear()
            
            logger.debug(f"Aggregating {len(messages_to_aggregate)} messages for {buffer_key}")
            
            # Build features
            features = await self.feature_builder.build_features(
                symbol=symbol,
                messages=messages_to_aggregate,
                message_type=message_type
            )
            
            if features:
                # Write features to Redis
                success = await self.redis_writer.write_features(symbol, features)
                
                if success:
                    self.stats["features_computed"] += 1
                    self.stats["features_written"] += 1
                    logger.debug(f"Wrote features for {symbol}: {features}")
                else:
                    self.stats["errors"] += 1
            
        except Exception as e:
            logger.error(f"Error aggregating buffer {buffer_key}: {e}", exc_info=True)
            self.stats["errors"] += 1
    
    async def _flush_all_features(self):
        """Flush all remaining features in buffers."""
        logger.info("Flushing all remaining features")
        
        for buffer_key, buffer in self._message_buffers.items():
            if buffer:
                await self._aggregate_buffer(buffer_key, buffer)
    
    async def _cleanup(self):
        """Clean up resources."""
        logger.info("Cleaning up stream aggregator resources")
        
        # Close Redis connection
        if self.redis_writer:
            await self.redis_writer.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on the stream aggregator."""
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "running": self._running,
            "stats": self.stats.copy(),
            "components": {}
        }
        
        # Check Kinesis consumer health
        try:
            kinesis_health = await self.kinesis_consumer.health_check()
            health_status["components"]["kinesis_consumer"] = kinesis_health
            
            if kinesis_health.get("status") != "healthy":
                health_status["status"] = "degraded"
        except Exception as e:
            health_status["components"]["kinesis_consumer"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "unhealthy"
        
        # Check Redis writer health
        try:
            redis_health = await self.redis_writer.health_check()
            health_status["components"]["redis_writer"] = redis_health
            
            if redis_health.get("status") != "healthy":
                health_status["status"] = "unhealthy"
        except Exception as e:
            health_status["components"]["redis_writer"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "unhealthy"
        
        # Check message freshness
        if self.stats["last_message_time"]:
            time_since_last = (
                datetime.now() - self.stats["last_message_time"]
            ).total_seconds()
            
            if time_since_last > 60:  # No messages for 1 minute
                health_status["status"] = "degraded"
                health_status["warning"] = f"No messages for {time_since_last:.0f} seconds"
        
        # Check buffer sizes
        total_buffered = sum(len(buffer) for buffer in self._message_buffers.values())
        if total_buffered > 5000:  # Large buffer accumulation
            health_status["status"] = "degraded"
            health_status["warning"] = f"Large buffer size: {total_buffered} messages"
        
        # Add buffer statistics
        health_status["buffer_stats"] = {
            "total_buffered_messages": total_buffered,
            "active_buffers": len(self._message_buffers),
            "buffer_details": {
                key: len(buffer) for key, buffer in self._message_buffers.items()
            }
        }
        
        # Calculate error rate
        total_processed = self.stats["messages_consumed"]
        if total_processed > 0:
            error_rate = self.stats["errors"] / total_processed
            if error_rate > 0.05:  # >5% error rate
                health_status["status"] = "degraded"
                health_status["warning"] = f"High error rate: {error_rate:.2%}"
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get aggregator statistics."""
        uptime = (datetime.now() - self.stats["start_time"]).total_seconds()
        
        stats = self.stats.copy()
        stats.update({
            "uptime_seconds": uptime,
            "messages_per_second": self.stats["messages_consumed"] / max(uptime, 1),
            "features_per_minute": (self.stats["features_computed"] / max(uptime, 1)) * 60,
            "error_rate": self.stats["errors"] / max(self.stats["messages_consumed"], 1),
            "buffer_stats": {
                "total_buffered": sum(len(buffer) for buffer in self._message_buffers.values()),
                "active_buffers": len(self._message_buffers)
            }
        })
        
        return stats