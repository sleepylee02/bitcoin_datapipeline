# Bitcoin Pipeline Reliability Documentation

## Overview

Comprehensive reliability engineering for the **10-second ahead Bitcoin price prediction pipeline** with **zero-downtime** requirements. This document details atomic re-anchoring procedures, fault tolerance mechanisms, and disaster recovery strategies that ensure continuous **sub-100ms inference** during all operational scenarios.

## Reliability Philosophy

### 1. Zero Downtime Principle
- **Hot Path Isolation**: Inference continues during all recovery operations
- **Atomic Operations**: State changes are all-or-nothing
- **Graceful Degradation**: Service quality reduces instead of failing
- **No Single Points of Failure**: Every component has redundancy

### 2. Fault Tolerance Hierarchy
```
Fault Type                    Response Strategy             Recovery Time
────────────────────────────────────────────────────────────────────────
SBE Stream Interruption     Automatic reconnection        <10 seconds
Redis Node Failure          Cluster failover               <5 seconds
Data Gap Detection           Atomic re-anchoring           <60 seconds
Model Loading Failure        Fallback prediction           <1 second
Infrastructure Outage        Multi-AZ failover             <2 minutes
```

### 3. Reliability Targets
- **Availability**: 99.9% (8.76 hours downtime/year)
- **Recovery Time**: <60 seconds for any single failure
- **Data Integrity**: Zero prediction downtime during recovery
- **Consistency**: Atomic state updates across all operations

## Atomic Re-anchoring System

### 1. Re-anchoring Triggers

#### Gap Detection Criteria
```python
GAP_DETECTION_RULES = {
    "sequence_gap": {
        "condition": "current_sequence - last_sequence > 1",
        "severity": "high",
        "action": "immediate_reanchor"
    },
    "time_gap": {
        "condition": "current_time - last_time > 5_seconds",
        "severity": "medium", 
        "action": "scheduled_reanchor"
    },
    "volume_anomaly": {
        "condition": "abs(current_volume - expected_volume) > 3_std_dev",
        "severity": "low",
        "action": "validation_reanchor"
    },
    "price_discontinuity": {
        "condition": "abs(price_change) > 0.01",  # >1% instant change
        "severity": "high",
        "action": "immediate_reanchor"
    },
    "connection_loss": {
        "condition": "websocket_disconnected_time > 30_seconds",
        "severity": "critical",
        "action": "emergency_reanchor"
    }
}
```

#### Automatic Trigger System
```python
class GapDetector:
    def __init__(self, config):
        self.last_sequence_id = None
        self.last_timestamp = None
        self.consecutive_gaps = 0
        self.gap_threshold = config.gap_threshold
        
    async def check_for_gaps(self, message: dict) -> bool:
        """Detect gaps and trigger re-anchoring if needed"""
        
        current_sequence = message.get("sequence_id")
        current_timestamp = message.get("event_ts")
        
        # Sequence gap detection
        if self.last_sequence_id and current_sequence:
            if current_sequence - self.last_sequence_id > 1:
                self.consecutive_gaps += 1
                logger.warning(f"Sequence gap detected: {self.last_sequence_id} → {current_sequence}")
                
                if self.consecutive_gaps >= self.gap_threshold:
                    await self.trigger_reanchor("sequence_gap")
                    return True
        
        # Time gap detection
        if self.last_timestamp and current_timestamp:
            time_gap = current_timestamp - self.last_timestamp
            if time_gap > 5_000_000:  # 5 seconds in microseconds
                logger.warning(f"Time gap detected: {time_gap / 1_000_000:.2f} seconds")
                await self.trigger_reanchor("time_gap")
                return True
        
        # Reset gap counter on normal message
        self.consecutive_gaps = 0
        self.last_sequence_id = current_sequence
        self.last_timestamp = current_timestamp
        
        return False
    
    async def trigger_reanchor(self, gap_type: str):
        """Trigger atomic re-anchoring process"""
        await self.reanchor_coordinator.schedule_reanchor(
            symbol="BTCUSDT",
            reason=gap_type,
            priority="high" if gap_type == "sequence_gap" else "medium"
        )
```

### 2. Atomic Re-anchoring Procedure

#### Phase 1: Coordination and Locking
```python
class AtomicReanchor:
    def __init__(self, redis_client, rest_client, config):
        self.redis = redis_client
        self.rest_client = rest_client
        self.config = config
        self.reanchor_timeout = 300  # 5 minutes max
        
    async def execute_reanchor(self, symbol: str, reason: str) -> bool:
        """Execute complete atomic re-anchoring procedure"""
        
        reanchor_id = f"reanchor_{symbol}_{int(time.time())}"
        
        try:
            # Phase 1: Acquire distributed lock
            lock_acquired = await self.acquire_reanchor_lock(symbol, reanchor_id)
            if not lock_acquired:
                logger.warning(f"Re-anchor already in progress for {symbol}")
                return False
            
            logger.info(f"Starting atomic re-anchor for {symbol} (reason: {reason})")
            start_time = time.time()
            
            # Phase 2: Collect fresh data
            fresh_data = await self.collect_fresh_data(symbol)
            
            # Phase 3: Build new state in temporary keys
            await self.build_temporary_state(symbol, fresh_data)
            
            # Phase 4: Validate new state
            validation_passed = await self.validate_new_state(symbol)
            if not validation_passed:
                raise ValueError("State validation failed")
            
            # Phase 5: Atomic swap
            swap_success = await self.perform_atomic_swap(symbol)
            if not swap_success:
                raise RuntimeError("Atomic swap failed")
            
            # Phase 6: Cleanup and verification
            await self.cleanup_and_verify(symbol)
            
            duration = time.time() - start_time
            logger.info(f"Re-anchor completed for {symbol} in {duration:.2f}s")
            
            return True
            
        except Exception as e:
            logger.error(f"Re-anchor failed for {symbol}: {e}")
            await self.cleanup_failed_reanchor(symbol)
            return False
            
        finally:
            await self.release_reanchor_lock(symbol, reanchor_id)
    
    async def acquire_reanchor_lock(self, symbol: str, reanchor_id: str) -> bool:
        """Acquire distributed lock to prevent concurrent re-anchoring"""
        
        lock_key = f"reanchor:{symbol}"
        
        # Use Redis SET with NX (not exists) and EX (expiry) for atomic locking
        result = await self.redis.set(
            lock_key, 
            reanchor_id, 
            ex=self.reanchor_timeout,  # 5-minute expiry
            nx=True  # Only set if not exists
        )
        
        return result is not None
    
    async def release_reanchor_lock(self, symbol: str, reanchor_id: str):
        """Release distributed lock safely"""
        
        lock_key = f"reanchor:{symbol}"
        
        # Use Lua script for atomic get-and-delete
        lua_script = """
        if redis.call("GET", KEYS[1]) == ARGV[1] then
            return redis.call("DEL", KEYS[1])
        else
            return 0
        end
        """
        
        await self.redis.eval(lua_script, 1, lock_key, reanchor_id)
```

#### Phase 2: Fresh Data Collection
```python
async def collect_fresh_data(self, symbol: str) -> dict:
    """Collect fresh market data from REST APIs in parallel"""
    
    try:
        # Parallel REST API calls for efficiency
        depth_task = self.rest_client.get_depth(symbol, limit=100)
        trades_task = self.rest_client.get_recent_trades(symbol, limit=1000)
        klines_task = self.rest_client.get_klines(symbol, interval="1m", limit=5)
        ticker_task = self.rest_client.get_24hr_ticker(symbol)
        
        # Wait for all data with timeout
        depth_data, trades_data, klines_data, ticker_data = await asyncio.wait_for(
            asyncio.gather(depth_task, trades_task, klines_task, ticker_task),
            timeout=10.0  # 10-second timeout
        )
        
        # Data validation
        if not depth_data or not depth_data.get("bids") or not depth_data.get("asks"):
            raise ValueError("Invalid depth data received")
            
        if not trades_data or len(trades_data) == 0:
            raise ValueError("No recent trades data received")
        
        # Filter recent trades (last 10 minutes)
        current_time = int(time.time() * 1000)
        recent_trades = [
            trade for trade in trades_data 
            if current_time - trade["time"] <= 600_000  # 10 minutes
        ]
        
        return {
            "depth": depth_data,
            "trades": recent_trades,
            "klines": klines_data,
            "ticker": ticker_data,
            "collection_timestamp": current_time
        }
        
    except asyncio.TimeoutError:
        raise RuntimeError("Data collection timeout - REST APIs unresponsive")
    except Exception as e:
        raise RuntimeError(f"Data collection failed: {e}")
```

#### Phase 3: Temporary State Building
```python
async def build_temporary_state(self, symbol: str, fresh_data: dict):
    """Build new state in temporary Redis keys"""
    
    # 1. Build temporary order book
    await self.build_temp_order_book(symbol, fresh_data["depth"])
    
    # 2. Build temporary trade statistics
    await self.build_temp_trade_stats(symbol, fresh_data["trades"])
    
    # 3. Build temporary feature vector
    await self.build_temp_features(symbol)
    
    logger.debug(f"Temporary state built for {symbol}")

async def build_temp_order_book(self, symbol: str, depth_data: dict):
    """Build temporary order book from REST depth snapshot"""
    
    temp_key = f"ob:new:{symbol}"
    
    # Extract best bid/ask
    bids = depth_data["bids"]
    asks = depth_data["asks"]
    
    if not bids or not asks:
        raise ValueError("Empty order book data")
    
    best_bid = float(bids[0][0])
    best_ask = float(asks[0][0])
    spread = best_ask - best_bid
    
    # Build order book hash
    ob_data = {
        "best_bid": str(best_bid),
        "best_ask": str(best_ask),
        "spread": str(spread),
        "spread_bp": str((spread / best_bid) * 10000),
        "last_update_id": str(depth_data["lastUpdateId"]),
        "ts_us": str(int(time.time() * 1_000_000)),
        "source": "rest"
    }
    
    # Add top 10 levels
    for i, (price, qty) in enumerate(bids[:10], 1):
        ob_data[f"bid{i}_p"] = price
        ob_data[f"bid{i}_q"] = qty
    
    for i, (price, qty) in enumerate(asks[:10], 1):
        ob_data[f"ask{i}_p"] = price
        ob_data[f"ask{i}_q"] = qty
    
    # Calculate order book metrics
    bid_values = [float(bids[i][0]) * float(bids[i][1]) for i in range(min(10, len(bids)))]
    ask_values = [float(asks[i][0]) * float(asks[i][1]) for i in range(min(10, len(asks)))]
    
    total_bid_value = sum(bid_values)
    total_ask_value = sum(ask_values)
    
    ob_data["bid_value_sum"] = str(total_bid_value)
    ob_data["ask_value_sum"] = str(total_ask_value)
    ob_data["ob_imbalance"] = str((total_bid_value - total_ask_value) / (total_bid_value + total_ask_value))
    
    # Store in temporary key
    await self.redis.hset(temp_key, mapping=ob_data)
    await self.redis.expire(temp_key, 600)  # 10-minute expiry

async def build_temp_trade_stats(self, symbol: str, trades_data: list):
    """Build temporary trade statistics from recent trades"""
    
    if not trades_data:
        raise ValueError("No trades data for statistics calculation")
    
    current_time = time.time()
    
    # Calculate 1-second window stats
    trades_1s = [
        trade for trade in trades_data
        if current_time - (trade["time"] / 1000) <= 1
    ]
    
    # Calculate 5-second window stats  
    trades_5s = [
        trade for trade in trades_data
        if current_time - (trade["time"] / 1000) <= 5
    ]
    
    # Build 1-second stats
    if trades_1s:
        stats_1s = self.calculate_trade_window_stats(trades_1s, window_seconds=1)
        await self.redis.hset(f"tr:new:{symbol}:1s", mapping=stats_1s)
        await self.redis.expire(f"tr:new:{symbol}:1s", 600)
    
    # Build 5-second stats
    if trades_5s:
        stats_5s = self.calculate_trade_window_stats(trades_5s, window_seconds=5)
        await self.redis.hset(f"tr:new:{symbol}:5s", mapping=stats_5s)
        await self.redis.expire(f"tr:new:{symbol}:5s", 600)

def calculate_trade_window_stats(self, trades: list, window_seconds: int) -> dict:
    """Calculate rolling trade statistics for a time window"""
    
    if not trades:
        return {}
    
    # Basic metrics
    total_volume = sum(float(trade["qty"]) for trade in trades)
    total_notional = sum(float(trade["price"]) * float(trade["qty"]) for trade in trades)
    trade_count = len(trades)
    
    # Buy/sell breakdown
    buy_trades = [trade for trade in trades if not trade["isBuyerMaker"]]
    sell_trades = [trade for trade in trades if trade["isBuyerMaker"]]
    
    buy_volume = sum(float(trade["qty"]) for trade in buy_trades)
    sell_volume = sum(float(trade["qty"]) for trade in sell_trades)
    
    # Price metrics
    prices = [float(trade["price"]) for trade in trades]
    vwap = total_notional / total_volume if total_volume > 0 else 0
    
    # Get current mid price for VWAP deviation
    mid_price = self.get_current_mid_price()
    vwap_minus_mid = vwap - mid_price if mid_price else 0
    
    return {
        "count": str(trade_count),
        "volume": str(total_volume),
        "notional": str(total_notional),
        "buy_volume": str(buy_volume),
        "sell_volume": str(sell_volume),
        "signed_volume": str(buy_volume - sell_volume),
        "vwap": str(vwap),
        "vwap_minus_mid": str(vwap_minus_mid),
        "trade_intensity": str(trade_count / window_seconds),
        "avg_trade_size": str(total_volume / trade_count if trade_count > 0 else 0),
        "last_ts_us": str(int(time.time() * 1_000_000))
    }
```

#### Phase 4: State Validation
```python
async def validate_new_state(self, symbol: str) -> bool:
    """Validate new temporary state before atomic swap"""
    
    try:
        # 1. Validate order book
        ob_valid = await self.validate_temp_order_book(symbol)
        if not ob_valid:
            logger.error("Order book validation failed")
            return False
        
        # 2. Validate trade statistics
        stats_valid = await self.validate_temp_trade_stats(symbol)
        if not stats_valid:
            logger.error("Trade statistics validation failed")
            return False
        
        # 3. Validate feature vector
        features_valid = await self.validate_temp_features(symbol)
        if not features_valid:
            logger.error("Feature vector validation failed")
            return False
        
        # 4. Cross-validation checks
        consistency_valid = await self.validate_data_consistency(symbol)
        if not consistency_valid:
            logger.error("Data consistency validation failed")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"State validation error: {e}")
        return False

async def validate_temp_order_book(self, symbol: str) -> bool:
    """Validate temporary order book state"""
    
    temp_ob = await self.redis.hgetall(f"ob:new:{symbol}")
    
    if not temp_ob:
        return False
    
    # Required fields check
    required_fields = ["best_bid", "best_ask", "spread", "bid1_p", "ask1_p"]
    for field in required_fields:
        if field not in temp_ob:
            logger.error(f"Missing required field: {field}")
            return False
    
    # Sanity checks
    try:
        best_bid = float(temp_ob["best_bid"])
        best_ask = float(temp_ob["best_ask"])
        spread = float(temp_ob["spread"])
        
        # Price validation
        if best_bid <= 0 or best_ask <= 0:
            logger.error("Invalid prices: bid/ask must be positive")
            return False
            
        if best_ask <= best_bid:
            logger.error("Invalid spread: ask must be greater than bid")
            return False
            
        if abs((best_ask - best_bid) - spread) > 0.01:
            logger.error("Spread calculation mismatch")
            return False
        
        # Reasonable price range check (within 10% of current price)
        current_price = await self.get_current_price_estimate()
        if current_price:
            if abs(best_bid - current_price) / current_price > 0.1:
                logger.error("Price deviation too large from current estimate")
                return False
        
        return True
        
    except (ValueError, TypeError) as e:
        logger.error(f"Order book validation error: {e}")
        return False
```

#### Phase 5: Atomic Swap Operation
```python
async def perform_atomic_swap(self, symbol: str) -> bool:
    """Perform atomic Redis key swap for zero-downtime re-anchoring"""
    
    try:
        # Build atomic transaction
        pipeline = self.redis.pipeline()
        
        # Verify temporary keys exist before swapping
        temp_keys = [
            f"ob:new:{symbol}",
            f"tr:new:{symbol}:1s", 
            f"tr:new:{symbol}:5s",
            f"feat:new:{symbol}"
        ]
        
        for key in temp_keys:
            exists = await self.redis.exists(key)
            if not exists:
                logger.error(f"Temporary key missing: {key}")
                return False
        
        # Atomic rename operations (all succeed or all fail)
        pipeline.rename(f"ob:new:{symbol}", f"ob:{symbol}")
        pipeline.rename(f"tr:new:{symbol}:1s", f"tr:{symbol}:1s")
        pipeline.rename(f"tr:new:{symbol}:5s", f"tr:{symbol}:5s") 
        pipeline.rename(f"feat:new:{symbol}", f"feat:{symbol}")
        
        # Set appropriate TTLs for renamed keys
        pipeline.expire(f"tr:{symbol}:1s", 300)  # 5-minute TTL
        pipeline.expire(f"tr:{symbol}:5s", 300)  # 5-minute TTL
        pipeline.expire(f"feat:{symbol}", 120)   # 2-minute TTL
        
        # Clear re-anchor lock
        pipeline.delete(f"reanchor:{symbol}")
        
        # Execute all operations atomically
        results = await pipeline.execute()
        
        # Verify all operations succeeded
        if all(result for result in results[:-1]):  # All renames should return True
            logger.info(f"Atomic swap completed successfully for {symbol}")
            return True
        else:
            logger.error(f"Atomic swap failed for {symbol}: {results}")
            return False
            
    except Exception as e:
        logger.error(f"Atomic swap error for {symbol}: {e}")
        return False
```

### 3. Failure Recovery Scenarios

#### Redis Cluster Node Failure
```python
class RedisFailureHandler:
    def __init__(self, redis_cluster, config):
        self.redis_cluster = redis_cluster
        self.config = config
        
    async def handle_node_failure(self, failed_node: str):
        """Handle Redis cluster node failure"""
        
        logger.warning(f"Redis node failure detected: {failed_node}")
        
        # 1. Check cluster health
        cluster_health = await self.check_cluster_health()
        
        if cluster_health["healthy_nodes"] >= cluster_health["required_nodes"]:
            # Cluster can continue operating
            logger.info("Cluster has sufficient healthy nodes, continuing operation")
            
            # Monitor automatic failover
            await self.monitor_automatic_failover(failed_node)
            
        else:
            # Cluster degraded, enable emergency mode
            logger.critical("Cluster critically degraded, enabling emergency mode")
            await self.enable_emergency_mode()
    
    async def monitor_automatic_failover(self, failed_node: str):
        """Monitor Redis cluster automatic failover"""
        
        failover_timeout = 30  # 30 seconds
        start_time = time.time()
        
        while time.time() - start_time < failover_timeout:
            cluster_info = await self.redis_cluster.cluster_info()
            
            if cluster_info["cluster_state"] == "ok":
                logger.info(f"Cluster failover completed for {failed_node}")
                return True
                
            await asyncio.sleep(1)
        
        logger.error(f"Cluster failover timeout for {failed_node}")
        await self.trigger_manual_intervention()
        return False
    
    async def enable_emergency_mode(self):
        """Enable emergency mode with degraded functionality"""
        
        # Switch to read-only mode
        await self.enable_read_only_mode()
        
        # Enable direct REST API fallback
        await self.enable_rest_fallback_mode()
        
        # Alert operations team
        await self.alert_ops_team("REDIS_CLUSTER_FAILURE")
```

#### SBE Stream Disconnection Recovery
```python
class SBEConnectionManager:
    def __init__(self, config):
        self.config = config
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 10
        self.reconnect_backoff = ExponentialBackoff(
            initial_delay=1.0,
            max_delay=60.0,
            multiplier=2.0
        )
        
    async def handle_connection_loss(self):
        """Handle SBE WebSocket connection loss"""
        
        logger.warning("SBE connection lost, starting recovery procedure")
        
        # 1. Immediate reconnection attempt
        if await self.attempt_immediate_reconnection():
            return True
        
        # 2. Exponential backoff reconnection
        if await self.attempt_backoff_reconnection():
            return True
        
        # 3. Trigger re-anchoring if reconnection fails
        logger.error("SBE reconnection failed, triggering re-anchor")
        await self.trigger_reanchor_recovery()
        
        # 4. Switch to degraded mode if re-anchor fails
        await self.enable_degraded_mode()
        
        return False
    
    async def attempt_immediate_reconnection(self) -> bool:
        """Attempt immediate reconnection (3 quick attempts)"""
        
        for attempt in range(3):
            try:
                logger.info(f"Immediate reconnection attempt {attempt + 1}/3")
                
                # Quick reconnection without delay
                connection = await self.sbe_client.connect()
                if connection and await self.verify_connection_health():
                    logger.info("Immediate SBE reconnection successful")
                    self.reconnect_attempts = 0
                    return True
                    
            except Exception as e:
                logger.warning(f"Immediate reconnection {attempt + 1} failed: {e}")
                
        return False
    
    async def attempt_backoff_reconnection(self) -> bool:
        """Attempt reconnection with exponential backoff"""
        
        while self.reconnect_attempts < self.max_reconnect_attempts:
            self.reconnect_attempts += 1
            delay = self.reconnect_backoff.calculate_delay(self.reconnect_attempts)
            
            logger.info(f"Backoff reconnection attempt {self.reconnect_attempts}/{self.max_reconnect_attempts} "
                       f"after {delay:.1f}s delay")
            
            await asyncio.sleep(delay)
            
            try:
                connection = await self.sbe_client.connect()
                if connection and await self.verify_connection_health():
                    logger.info("Backoff SBE reconnection successful")
                    self.reconnect_attempts = 0
                    return True
                    
            except Exception as e:
                logger.warning(f"Backoff reconnection {self.reconnect_attempts} failed: {e}")
        
        logger.error("All SBE reconnection attempts exhausted")
        return False
    
    async def verify_connection_health(self) -> bool:
        """Verify SBE connection is healthy and receiving data"""
        
        # Wait for messages for 10 seconds
        message_timeout = 10.0
        start_time = time.time()
        
        while time.time() - start_time < message_timeout:
            if self.sbe_client.last_message_time and \
               time.time() - self.sbe_client.last_message_time < 5.0:
                return True
            await asyncio.sleep(0.5)
        
        logger.warning("SBE connection not receiving messages")
        return False
```

#### Model Loading and Inference Failure
```python
class ModelFailureHandler:
    def __init__(self, model_registry, config):
        self.model_registry = model_registry
        self.config = config
        self.fallback_models = []
        
    async def handle_model_failure(self, error: Exception):
        """Handle model loading or inference failure"""
        
        logger.error(f"Model failure detected: {error}")
        
        # 1. Attempt model reload
        if await self.attempt_model_reload():
            return True
        
        # 2. Load fallback model
        if await self.load_fallback_model():
            return True
        
        # 3. Enable simple prediction fallback
        await self.enable_simple_fallback()
        
        # 4. Alert for manual intervention
        await self.alert_model_failure()
        
        return False
    
    async def attempt_model_reload(self) -> bool:
        """Attempt to reload the current model"""
        
        try:
            logger.info("Attempting model reload")
            
            # Clear current model
            self.inference_service.clear_model()
            
            # Reload from registry
            current_model = await self.model_registry.get_current_model()
            model_loaded = await self.inference_service.load_model(current_model)
            
            if model_loaded:
                # Test model with dummy prediction
                test_successful = await self.test_model_inference()
                if test_successful:
                    logger.info("Model reload successful")
                    return True
            
        except Exception as e:
            logger.error(f"Model reload failed: {e}")
        
        return False
    
    async def load_fallback_model(self) -> bool:
        """Load a fallback model version"""
        
        fallback_models = await self.model_registry.get_fallback_models()
        
        for fallback_model in fallback_models:
            try:
                logger.info(f"Attempting fallback model: {fallback_model['version']}")
                
                model_loaded = await self.inference_service.load_model(fallback_model)
                
                if model_loaded and await self.test_model_inference():
                    logger.info(f"Fallback model loaded: {fallback_model['version']}")
                    return True
                    
            except Exception as e:
                logger.warning(f"Fallback model {fallback_model['version']} failed: {e}")
        
        return False
    
    async def enable_simple_fallback(self):
        """Enable simple prediction fallback (linear trend)"""
        
        logger.warning("Enabling simple prediction fallback")
        
        self.inference_service.enable_fallback_mode(
            mode="linear_trend",
            confidence=0.1  # Very low confidence
        )
        
        # Continue service with degraded predictions
        await self.notify_degraded_service()
```

## Disaster Recovery

### 1. Multi-AZ Deployment Strategy

#### Infrastructure Redundancy
```yaml
disaster_recovery:
  primary_region: "us-east-1"
  secondary_region: "us-west-2"
  
  service_deployment:
    inference_service:
      primary_az: ["us-east-1a", "us-east-1b"]
      secondary_az: ["us-west-2a", "us-west-2b"]
      auto_failover: true
      rto: "2 minutes"  # Recovery Time Objective
      rpo: "30 seconds"  # Recovery Point Objective
      
    aggregator_service:
      primary_az: ["us-east-1a", "us-east-1b"]
      failover_mode: "active-passive"
      data_replication: "real-time"
      
    redis_cluster:
      multi_az: true
      replica_count: 3
      automatic_failover: true
      backup_retention: "7 days"
```

#### Failover Automation
```python
class DisasterRecoveryManager:
    def __init__(self, config):
        self.config = config
        self.health_checker = HealthChecker()
        self.failover_threshold = 3  # Consecutive failures
        
    async def monitor_regional_health(self):
        """Monitor regional health and trigger failover if needed"""
        
        while True:
            try:
                # Check primary region health
                primary_health = await self.check_regional_health("us-east-1")
                
                if not primary_health["healthy"]:
                    await self.handle_regional_failure("us-east-1")
                
                await asyncio.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logger.error(f"Regional health monitoring error: {e}")
    
    async def handle_regional_failure(self, failed_region: str):
        """Handle complete regional failure"""
        
        logger.critical(f"Regional failure detected: {failed_region}")
        
        # 1. Verify failure is persistent
        if not await self.verify_persistent_failure(failed_region):
            return
        
        # 2. Initiate failover to secondary region
        await self.initiate_regional_failover(failed_region)
        
        # 3. Update DNS and load balancer
        await self.update_traffic_routing(failed_region)
        
        # 4. Verify secondary region health
        await self.verify_failover_success()
        
        # 5. Alert operations team
        await self.alert_regional_failover(failed_region)
```

### 2. Data Backup and Recovery

#### Automated Backup Strategy
```python
class BackupManager:
    def __init__(self, config):
        self.config = config
        
    async def execute_backup_strategy(self):
        """Execute comprehensive backup strategy"""
        
        # 1. Redis snapshot backup
        await self.backup_redis_state()
        
        # 2. RDS automated backup verification
        await self.verify_rds_backups()
        
        # 3. S3 cross-region replication check
        await self.verify_s3_replication()
        
        # 4. Model artifact backup
        await self.backup_model_artifacts()
    
    async def backup_redis_state(self):
        """Backup critical Redis state"""
        
        critical_keys = [
            "ob:BTCUSDT",
            "tr:BTCUSDT:*",
            "feat:BTCUSDT",
            "pred:BTCUSDT"
        ]
        
        backup_data = {}
        
        for key_pattern in critical_keys:
            if "*" in key_pattern:
                keys = await self.redis.keys(key_pattern)
            else:
                keys = [key_pattern]
            
            for key in keys:
                key_type = await self.redis.type(key)
                
                if key_type == "hash":
                    backup_data[key] = await self.redis.hgetall(key)
                elif key_type == "string":
                    backup_data[key] = await self.redis.get(key)
        
        # Store backup in S3
        backup_key = f"redis-backups/{datetime.now().isoformat()}/state.json"
        await self.s3_client.put_object(
            Bucket="bitcoin-backups",
            Key=backup_key,
            Body=json.dumps(backup_data),
            StorageClass="STANDARD_IA"
        )
```

### 3. Recovery Testing

#### Automated Recovery Testing
```python
class RecoveryTester:
    def __init__(self, config):
        self.config = config
        
    async def execute_recovery_tests(self):
        """Execute automated recovery tests"""
        
        test_results = {}
        
        # 1. Test Redis failover
        test_results["redis_failover"] = await self.test_redis_failover()
        
        # 2. Test service failover
        test_results["service_failover"] = await self.test_service_failover()
        
        # 3. Test re-anchoring procedure
        test_results["reanchor_test"] = await self.test_reanchor_procedure()
        
        # 4. Test model fallback
        test_results["model_fallback"] = await self.test_model_fallback()
        
        # 5. Generate recovery report
        await self.generate_recovery_report(test_results)
        
        return test_results
    
    async def test_reanchor_procedure(self) -> dict:
        """Test atomic re-anchoring in controlled environment"""
        
        test_start = time.time()
        
        try:
            # 1. Simulate gap detection
            await self.simulate_gap_detection()
            
            # 2. Trigger re-anchor
            reanchor_success = await self.trigger_test_reanchor()
            
            # 3. Verify state consistency
            state_consistent = await self.verify_state_consistency()
            
            # 4. Verify inference continuity
            inference_continuous = await self.verify_inference_continuity()
            
            test_duration = time.time() - test_start
            
            return {
                "success": reanchor_success and state_consistent and inference_continuous,
                "duration_seconds": test_duration,
                "reanchor_success": reanchor_success,
                "state_consistent": state_consistent,
                "inference_continuous": inference_continuous
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "duration_seconds": time.time() - test_start
            }
```

## Reliability Metrics and SLAs

### 1. Service Level Objectives (SLOs)

#### Availability SLOs
```yaml
service_level_objectives:
  availability:
    target: 99.9%  # 8.76 hours downtime per year
    measurement_window: "30 days"
    error_budget: 0.1%  # 43.2 minutes per month
    
  inference_latency:
    p99_target: "100ms"
    p95_target: "50ms"
    measurement_window: "1 hour"
    
  prediction_accuracy:
    directional_accuracy: ">55%"
    measurement_window: "24 hours"
    evaluation_delay: "10 seconds"  # Wait for actual outcome
    
  recovery_time:
    reanchor_operation: "<60 seconds"
    service_restart: "<120 seconds"
    regional_failover: "<300 seconds"
```

### 2. Reliability Metrics Dashboard

#### Key Reliability Indicators
```yaml
reliability_dashboard:
  real_time_panels:
    - name: "System Health Score"
      metric: "overall_reliability_score"
      target: ">0.99"
      
    - name: "Error Budget Remaining"
      metric: "error_budget_remaining_percent"
      target: ">10%"
      
    - name: "Mean Time to Recovery"
      metric: "avg_recovery_time_seconds"
      target: "<60s"
      
    - name: "Successful Re-anchors"
      metric: "reanchor_success_rate"
      target: ">99%"
      
  historical_panels:
    - name: "Availability Trend (30 days)"
      metric: "availability_percentage"
      time_range: "30d"
      
    - name: "Incident Frequency"
      metric: "incidents_per_week"
      target: "<2"
```

This comprehensive reliability framework ensures the Bitcoin prediction pipeline maintains continuous operation with sub-100ms inference latency through sophisticated fault tolerance, atomic re-anchoring procedures, and automated disaster recovery capabilities.