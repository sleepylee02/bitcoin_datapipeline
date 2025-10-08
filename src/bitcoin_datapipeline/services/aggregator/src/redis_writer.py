"""Redis writer for storing aggregated features."""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional
import redis.asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError

from .config.settings import AggregatorConfig


logger = logging.getLogger(__name__)


class RedisWriter:
    """Writes aggregated features to Redis for real-time inference."""
    
    def __init__(self, config: AggregatorConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        
        # Statistics
        self.stats = {
            "features_written": 0,
            "write_errors": 0,
            "connection_errors": 0,
            "last_write_time": None
        }
        
        logger.info(f"RedisWriter initialized for {config.redis.host}:{config.redis.port}")
    
    async def initialize(self):
        """Initialize Redis connection."""
        try:
            # Create Redis connection
            self.redis_client = redis.Redis(
                host=self.config.redis.host,
                port=self.config.redis.port,
                password=self.config.redis.password,
                db=self.config.redis.db,
                socket_timeout=self.config.redis.socket_timeout,
                socket_connect_timeout=self.config.redis.socket_connect_timeout,
                health_check_interval=30,
                retry_on_timeout=True,
                decode_responses=True
            )
            
            # Test connection
            await self.redis_client.ping()
            
            logger.info("Redis connection initialized successfully")
            
        except Exception as e:
            logger.error(f"Failed to initialize Redis connection: {e}")
            self.stats["connection_errors"] += 1
            raise
    
    async def close(self):
        """Close Redis connection."""
        if self.redis_client:
            logger.info("Closing Redis connection")
            await self.redis_client.close()
            self.redis_client = None
    
    async def write_features(self, symbol: str, features: Dict[str, Any]) -> bool:
        """Write features to Redis with TTL."""
        
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return False
        
        try:
            # Create Redis key
            timestamp = features.get("timestamp", int(datetime.now().timestamp()))
            redis_key = f"{self.config.redis.key_prefix}:{symbol}:{timestamp}"
            
            # Serialize features to JSON
            features_json = json.dumps(features, default=str)
            
            # Write to Redis with TTL
            await self.redis_client.setex(
                redis_key,
                self.config.redis.ttl_seconds,
                features_json
            )
            
            # Also write latest features with a fixed key for easy access
            latest_key = f"{self.config.redis.key_prefix}:{symbol}:latest"
            await self.redis_client.setex(
                latest_key,
                self.config.redis.ttl_seconds,
                features_json
            )
            
            # Update statistics
            self.stats["features_written"] += 1
            self.stats["last_write_time"] = datetime.now()
            
            logger.debug(f"Wrote features to Redis: {redis_key}")
            return True
            
        except (ConnectionError, TimeoutError) as e:
            logger.error(f"Redis connection error writing features: {e}")
            self.stats["connection_errors"] += 1
            return False
        
        except Exception as e:
            logger.error(f"Error writing features to Redis: {e}", exc_info=True)
            self.stats["write_errors"] += 1
            return False
    
    async def get_latest_features(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get the latest features for a symbol."""
        
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return None
        
        try:
            latest_key = f"{self.config.redis.key_prefix}:{symbol}:latest"
            features_json = await self.redis_client.get(latest_key)
            
            if features_json:
                return json.loads(features_json)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting latest features for {symbol}: {e}")
            return None
    
    async def get_features_by_timestamp(
        self, 
        symbol: str, 
        timestamp: int
    ) -> Optional[Dict[str, Any]]:
        """Get features for a specific timestamp."""
        
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return None
        
        try:
            redis_key = f"{self.config.redis.key_prefix}:{symbol}:{timestamp}"
            features_json = await self.redis_client.get(redis_key)
            
            if features_json:
                return json.loads(features_json)
            
            return None
            
        except Exception as e:
            logger.error(f"Error getting features for {symbol} at {timestamp}: {e}")
            return None
    
    async def get_recent_features(
        self, 
        symbol: str, 
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Get recent features for a symbol."""
        
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return []
        
        try:
            # Pattern to match timestamped keys for the symbol
            pattern = f"{self.config.redis.key_prefix}:{symbol}:*"
            
            # Get all matching keys
            keys = await self.redis_client.keys(pattern)
            
            # Filter out the 'latest' key and sort by timestamp
            timestamped_keys = [
                key for key in keys 
                if not key.endswith(':latest')
            ]
            
            # Sort by timestamp (extract from key)
            timestamped_keys.sort(
                key=lambda k: int(k.split(':')[-1]),
                reverse=True
            )
            
            # Get the most recent features
            recent_features = []
            for key in timestamped_keys[:limit]:
                features_json = await self.redis_client.get(key)
                if features_json:
                    features = json.loads(features_json)
                    recent_features.append(features)
            
            return recent_features
            
        except Exception as e:
            logger.error(f"Error getting recent features for {symbol}: {e}")
            return []
    
    async def delete_features(self, symbol: str, timestamp: Optional[int] = None) -> bool:
        """Delete features for a symbol."""
        
        if not self.redis_client:
            logger.error("Redis client not initialized")
            return False
        
        try:
            if timestamp:
                # Delete specific timestamp
                redis_key = f"{self.config.redis.key_prefix}:{symbol}:{timestamp}"
                await self.redis_client.delete(redis_key)
            else:
                # Delete all features for symbol
                pattern = f"{self.config.redis.key_prefix}:{symbol}:*"
                keys = await self.redis_client.keys(pattern)
                
                if keys:
                    await self.redis_client.delete(*keys)
            
            return True
            
        except Exception as e:
            logger.error(f"Error deleting features for {symbol}: {e}")
            return False
    
    async def cleanup_expired_keys(self) -> int:
        """Clean up expired keys (manual cleanup)."""
        
        if not self.redis_client:
            return 0
        
        try:
            # Get all feature keys
            pattern = f"{self.config.redis.key_prefix}:*"
            keys = await self.redis_client.keys(pattern)
            
            expired_count = 0
            current_time = int(datetime.now().timestamp())
            
            for key in keys:
                if key.endswith(':latest'):
                    continue
                
                try:
                    # Extract timestamp from key
                    timestamp = int(key.split(':')[-1])
                    
                    # Check if expired
                    if current_time - timestamp > self.config.redis.ttl_seconds:
                        await self.redis_client.delete(key)
                        expired_count += 1
                
                except (ValueError, IndexError):
                    # Skip malformed keys
                    continue
            
            if expired_count > 0:
                logger.info(f"Cleaned up {expired_count} expired Redis keys")
            
            return expired_count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired keys: {e}")
            return 0
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on Redis connection."""
        
        health_status = {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "stats": self.stats.copy()
        }
        
        try:
            if not self.redis_client:
                health_status["status"] = "unhealthy"
                health_status["error"] = "Redis client not initialized"
                return health_status
            
            # Test Redis connectivity
            ping_result = await self.redis_client.ping()
            
            if not ping_result:
                health_status["status"] = "unhealthy"
                health_status["error"] = "Redis ping failed"
                return health_status
            
            # Get Redis info
            info = await self.redis_client.info()
            
            health_status["redis_info"] = {
                "redis_version": info.get("redis_version"),
                "used_memory_human": info.get("used_memory_human"),
                "connected_clients": info.get("connected_clients"),
                "uptime_in_seconds": info.get("uptime_in_seconds")
            }
            
            # Check recent activity
            if self.stats["last_write_time"]:
                last_write = self.stats["last_write_time"]
                time_since_write = (datetime.now() - last_write).total_seconds()
                
                if time_since_write > 300:  # No writes for 5 minutes
                    health_status["status"] = "degraded"
                    health_status["warning"] = f"No writes for {time_since_write:.0f} seconds"
            
            # Check error rates
            total_operations = self.stats["features_written"] + self.stats["write_errors"]
            if total_operations > 0:
                error_rate = self.stats["write_errors"] / total_operations
                if error_rate > 0.05:  # >5% error rate
                    health_status["status"] = "degraded"
                    health_status["warning"] = f"High error rate: {error_rate:.2%}"
        
        except Exception as e:
            health_status["status"] = "unhealthy"
            health_status["error"] = str(e)
        
        return health_status
    
    def get_stats(self) -> Dict[str, Any]:
        """Get Redis writer statistics."""
        stats = self.stats.copy()
        
        # Calculate rates
        if self.stats["last_write_time"]:
            uptime = (datetime.now() - self.stats["last_write_time"]).total_seconds()
            stats["writes_per_second"] = self.stats["features_written"] / max(uptime, 1)
        
        return stats