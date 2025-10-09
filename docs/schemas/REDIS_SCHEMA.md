# Redis Hot State Schema Documentation

## Overview

Redis serves as the **hot state cache** for the Bitcoin price prediction pipeline, enabling **sub-100ms inference latency** through optimized key-value storage. This document defines the complete Redis schema, TTL strategies, and atomic operation patterns used for 10-second ahead predictions.

## Schema Design Principles

### 1. Hot Path Optimization
- **Fast Reads**: Optimized for <1ms read operations
- **Atomic Updates**: Use Redis transactions for consistency
- **Memory Efficiency**: Strategic TTL management and data types
- **Zero Downtime**: Atomic key swapping during re-anchoring

### 2. Key Naming Convention
```
{prefix}:{symbol}:{qualifier}
```

Where:
- `prefix`: Data type identifier
- `symbol`: Trading pair (always BTCUSDT)
- `qualifier`: Optional window or identifier

### 3. TTL Strategy
```
Data Type           TTL      Reason
─────────────────────────────────────────
Order Books         None     Always live state
Trade Stats         5min     Rolling windows
Features            2min     Inference freshness
Predictions         10min    Recent predictions
Re-anchor Flags     5min     Prevent deadlock
Temporary Keys      10min    Safety during operations
```

## Core Schema Components

### 1. Order Book State

#### Primary Key: `ob:{symbol}`
```redis
ob:BTCUSDT (HASH)
```

#### Schema Definition
```redis
# Best Bid/Ask (Critical for spreads)
best_bid        "45229.50"         # Best bid price
best_ask        "45231.00"         # Best ask price  
spread          "1.50"             # Absolute spread
spread_bp       "3.32"             # Spread in basis points

# Top 10 Bid Levels
bid1_p          "45229.50"         # Bid level 1 price
bid1_q          "1.5"              # Bid level 1 quantity
bid2_p          "45229.00"         # Bid level 2 price
bid2_q          "2.1"              # Bid level 2 quantity
...
bid10_p         "45225.00"         # Bid level 10 price
bid10_q         "3.2"              # Bid level 10 quantity

# Top 10 Ask Levels
ask1_p          "45231.00"         # Ask level 1 price
ask1_q          "1.2"              # Ask level 1 quantity
ask2_p          "45231.50"         # Ask level 2 price
ask2_q          "1.8"              # Ask level 2 quantity
...
ask10_p         "45235.00"         # Ask level 10 price
ask10_q         "1.9"              # Ask level 10 quantity

# Order Book Metrics
bid_value_sum   "1525840.75"       # Sum of bid1-10 values
ask_value_sum   "1526235.25"       # Sum of ask1-10 values
ob_imbalance    "0.031"            # (bid_val - ask_val) / total_val
weighted_mid    "45230.25"         # Volume-weighted mid price

# Latest Trade Information
last_trade_price "45230.50"        # Most recent trade price
last_trade_ts   "1638360000123456" # Last trade timestamp (μs)

# Metadata
last_update_id  "123456789"        # For sequence validation
ts_us           "1638360000123456" # Order book timestamp (μs)
source          "sbe"              # Data source ("sbe" or "rest")
```

#### Update Patterns
```python
# Atomic order book update
pipeline = redis.pipeline()
pipeline.hset("ob:BTCUSDT", "best_bid", new_bid)
pipeline.hset("ob:BTCUSDT", "best_ask", new_ask)
pipeline.hset("ob:BTCUSDT", "spread", new_ask - new_bid)
pipeline.hset("ob:BTCUSDT", "ts_us", timestamp_us)
await pipeline.execute()
```

### 2. Rolling Trade Statistics

#### 1-Second Window: `tr:{symbol}:1s`
```redis
tr:BTCUSDT:1s (HASH)             # TTL: 5 minutes
```

#### Schema Definition
```redis
# Basic Trade Metrics
count           "15"              # Number of trades in window
volume          "12.567"          # Total volume
notional        "567890.12"       # Total notional value
avg_price       "45230.25"        # Average trade price

# Buy/Sell Breakdown
buy_count       "9"               # Number of buy trades
sell_count      "6"               # Number of sell trades
buy_volume      "8.234"           # Total buy volume
sell_volume     "4.333"           # Total sell volume
signed_volume   "3.901"           # buy_volume - sell_volume

# Price Metrics
vwap            "45230.18"        # Volume-weighted average price
vwap_minus_mid  "0.05"            # VWAP deviation from mid
price_std       "0.23"            # Price standard deviation
price_range     "1.20"            # max_price - min_price

# Timing Metrics
interarrival_mean "0.067"         # Mean seconds between trades
interarrival_var  "0.023"         # Variance of inter-arrival times
first_ts_us     "1638360000000000" # First trade timestamp
last_ts_us      "1638360001000000" # Last trade timestamp

# Derived Features
trade_intensity "15.0"            # Trades per second
dollar_intensity "567890.12"      # Notional per second
avg_trade_size  "0.838"           # Average trade size

# Quality Metrics
data_completeness "1.0"           # Data quality indicator (0-1)
update_count    "15"              # Number of updates in window
```

#### 5-Second Window: `tr:{symbol}:5s`
```redis
tr:BTCUSDT:5s (HASH)             # TTL: 5 minutes
```

#### Schema Definition
```redis
# Extended 5-Second Metrics (similar structure to 1s)
count           "75"              # Trades in 5-second window
volume          "62.835"          # 5-second volume
notional        "2839450.60"      # 5-second notional
signed_volume   "8.745"           # 5-second buy/sell imbalance
vwap            "45225.30"        # 5-second VWAP
vwap_minus_mid  "0.12"            # 5-second VWAP deviation
trade_intensity "15.0"            # Average trades per second
price_momentum  "0.0023"          # 5-second price momentum
volume_acceleration "1.2"         # Volume acceleration
last_ts_us      "1638360005000000" # Window end timestamp
```

#### Update Patterns
```python
# Rolling window update
async def update_trade_statistics(trades: List[dict], window: int):
    stats = calculate_rolling_stats(trades, window_seconds=window)
    
    await redis.hset(f"tr:BTCUSDT:{window}s", mapping=stats)
    await redis.expire(f"tr:BTCUSDT:{window}s", 300)  # 5-minute TTL
```

### 3. Feature Vectors

#### Primary Key: `feat:{symbol}`
```redis
feat:BTCUSDT (HASH)              # TTL: 2 minutes
```

#### Schema Definition
```redis
# Price Features
price           "45230.50"        # Latest trade price
mid_price       "45230.25"        # Order book mid price
ret_1s          "0.0002"          # 1-second return
ret_5s          "0.0015"          # 5-second return
ret_10s         "0.0032"          # 10-second return

# Volume Features
volume_1s       "12.567"          # 1-second volume
volume_5s       "62.835"          # 5-second volume
vol_imbalance_1s "0.031"          # 1s buy/sell imbalance
vol_imbalance_5s "0.064"          # 5s buy/sell imbalance

# Order Book Features
spread_bp       "3.32"            # Spread in basis points
ob_imbalance    "0.031"           # Order book imbalance
bid_strength    "1525840.75"      # Total bid value (L1-L10)
ask_strength    "1526235.25"      # Total ask value (L1-L10)

# Trade Flow Features
trade_intensity_1s "15.0"         # Trades per second
trade_intensity_5s "15.0"         # 5s average trades/sec
avg_trade_size_1s  "0.838"        # Average trade size
dollar_volume_1s   "567890.12"    # Dollar volume per second

# Technical Indicators
vwap_dev_1s     "0.05"            # VWAP deviation from mid
vwap_dev_5s     "0.12"            # 5s VWAP deviation
price_volatility "0.0023"         # Rolling volatility
momentum        "0.0032"          # Price momentum

# Advanced Features (Computed)
price_acceleration "0.0005"       # Change in momentum
volume_momentum "48.23"           # Volume * momentum
vol_adj_ret_1s  "0.087"           # Volatility-adjusted return
volume_change_5s "0.15"           # Volume rate of change
dollar_intensity "12567.89"       # Dollar volume intensity
spread_adj_imbalance "9.32"       # Spread-adjusted imbalance
bid_ask_ratio   "1.002"           # Bid/ask strength ratio

# Temporal Features
hour_sin        "0.866"           # Sin(hour * 2π / 24)
hour_cos        "0.500"           # Cos(hour * 2π / 24)
is_us_hours     "1"               # US trading hours indicator
is_asia_hours   "0"               # Asia trading hours indicator

# Interaction Features
price_volume_int "0.00003"        # Price * volume interaction
spread_momentum_int "0.011"       # Spread * momentum interaction
vol_imbalance_int "0.00007"       # Volatility * imbalance interaction

# Metadata
feature_ts      "1638360000"      # Feature computation timestamp
data_age_ms     "150"             # Age of underlying data (ms)
completeness    "1.0"             # Feature completeness ratio (0-1)
update_count    "1"               # Number of updates
computation_ms  "12"              # Feature computation time
```

#### Update Patterns
```python
# Feature vector update
async def compute_and_cache_features(symbol: str):
    features = await compute_feature_vector(symbol)
    
    await redis.hset(f"feat:{symbol}", mapping=features)
    await redis.expire(f"feat:{symbol}", 120)  # 2-minute TTL
```

### 4. Prediction Cache

#### Primary Key: `pred:{symbol}`
```redis
pred:BTCUSDT (HASH)              # TTL: 10 minutes
```

#### Schema Definition
```redis
# Prediction Results
predicted_price "45235.75"       # Price 10 seconds ahead
current_price   "45230.50"       # Price at prediction time
price_change    "5.25"           # Predicted change
return_10s      "0.000116"       # Predicted 10s return

# Confidence and Quality
confidence      "0.87"           # Model confidence (0-1)
directional_conf "0.92"          # Direction confidence
magnitude_conf  "0.82"           # Magnitude confidence

# Timing Information
prediction_ts   "1638360000"     # When prediction was made (epoch s)
target_ts       "1638360010"     # Target time (10s ahead)
prediction_ts_ms "1638360000000" # Prediction time (epoch ms)
target_ts_ms    "1638360010000"  # Target time (epoch ms)

# Model Information
model_version   "v1.2.3"        # Model version used
model_hash      "abc123def"      # Model file hash
feature_version "2023-12-15"     # Feature schema version

# Performance Metrics
latency_ms      "45"             # Total inference latency
feature_read_ms "3"              # Redis read time
model_infer_ms  "28"             # Model inference time
post_process_ms "2"              # Post-processing time

# Data Quality
features_age_ms "120"            # Age of input features
feature_completeness "0.98"      # Feature quality score
data_sources    "sbe"            # Data sources used

# Prediction Metadata
source          "redis"          # "redis" or "fallback"
prediction_id   "pred_123456"    # Unique prediction ID
sequence_num    "1234"           # Prediction sequence number
```

#### Update Patterns
```python
# Prediction caching
async def cache_prediction(prediction: PredictionResult):
    prediction_data = {
        "predicted_price": str(prediction.predicted_price),
        "current_price": str(prediction.current_price),
        "confidence": str(prediction.confidence),
        "prediction_ts": str(prediction.timestamp // 1000),
        "target_ts": str((prediction.timestamp + 10000) // 1000),
        "model_version": prediction.model_version,
        "latency_ms": str(prediction.inference_latency_ms),
        "source": prediction.source
    }
    
    await redis.hset(f"pred:{prediction.symbol}", mapping=prediction_data)
    await redis.expire(f"pred:{prediction.symbol}", 600)  # 10-minute TTL
```

### 5. System Control Keys

#### Re-anchor Flag: `reanchor:{symbol}`
```redis
reanchor:BTCUSDT "1"              # TTL: 5 minutes (300s)
```

#### Purpose and Usage
- **Coordination**: Prevents concurrent re-anchor operations
- **Safety**: Ensures atomic operations during recovery
- **Timeout**: Automatic cleanup after 5 minutes

```python
# Re-anchor coordination
async def start_reanchor(symbol: str) -> bool:
    # Set flag with TTL
    result = await redis.set(f"reanchor:{symbol}", "1", ex=300, nx=True)
    return result is not None  # True if successfully set
```

#### Health Check Key: `health:{service}`
```redis
health:aggregator (HASH)         # TTL: 1 minute
```

#### Schema Definition
```redis
status          "healthy"        # Service status
last_update     "1638360000"     # Last health update
version         "1.2.3"          # Service version
uptime_seconds  "86400"          # Service uptime
memory_mb       "256"            # Memory usage
cpu_percent     "15.5"           # CPU utilization
```

## Atomic Re-anchoring Schema

### Temporary Key Pattern
During re-anchoring, temporary keys are created with `.new.` qualifier:

```redis
# Temporary keys during re-anchor
ob:new:BTCUSDT              # New order book state
tr:new:BTCUSDT:1s           # New 1s trade stats
tr:new:BTCUSDT:5s           # New 5s trade stats
feat:new:BTCUSDT            # New feature vector
```

### Atomic Swap Operations
```python
async def atomic_reanchor_swap(symbol: str):
    """Perform atomic key swap for zero-downtime re-anchoring"""
    
    pipeline = redis.pipeline()
    
    # Atomic rename operations (all succeed or all fail)
    pipeline.rename(f"ob:new:{symbol}", f"ob:{symbol}")
    pipeline.rename(f"tr:new:{symbol}:1s", f"tr:{symbol}:1s")
    pipeline.rename(f"tr:new:{symbol}:5s", f"tr:{symbol}:5s")
    pipeline.rename(f"feat:new:{symbol}", f"feat:{symbol}")
    
    # Set proper TTLs
    pipeline.expire(f"tr:{symbol}:1s", 300)
    pipeline.expire(f"tr:{symbol}:5s", 300)
    pipeline.expire(f"feat:{symbol}", 120)
    
    # Clear re-anchor flag
    pipeline.delete(f"reanchor:{symbol}")
    
    # Execute atomically
    results = await pipeline.execute()
    return all(results)
```

## Data Types and Optimization

### 1. Hash vs String Trade-offs

#### Hash Benefits (Current Choice)
- **Field-level updates**: Update individual fields without full object replacement
- **Memory efficiency**: Redis optimizes small hashes
- **Atomic field operations**: `HSET`, `HGET`, `HMGET` operations
- **Schema flexibility**: Easy to add/remove fields

#### Usage Pattern
```python
# Efficient field updates
await redis.hset("feat:BTCUSDT", "price", new_price)
await redis.hset("feat:BTCUSDT", "volume_1s", new_volume)

# Batch field reads
features = await redis.hmget("feat:BTCUSDT", 
                           ["price", "volume_1s", "spread_bp"])
```

### 2. Memory Optimization

#### TTL Strategy Implementation
```python
TTL_SETTINGS = {
    "ob:*": None,           # No TTL - always live
    "tr:*": 300,           # 5 minutes
    "feat:*": 120,         # 2 minutes  
    "pred:*": 600,         # 10 minutes
    "reanchor:*": 300,     # 5 minutes
    "*.new.*": 600,        # 10 minutes (safety)
    "health:*": 60         # 1 minute
}
```

#### Memory Usage Estimation
```
Component           Keys    Memory/Key    Total Memory
─────────────────────────────────────────────────────
Order Books         1       ~8KB          8KB
Trade Stats (1s)    1       ~2KB          2KB
Trade Stats (5s)    1       ~2KB          2KB
Features            1       ~3KB          3KB
Predictions         1       ~1KB          1KB
Control Keys        ~5      ~100B         500B
─────────────────────────────────────────────────────
Total per Symbol                          ~16.5KB
```

### 3. Connection Optimization

#### Connection Pool Configuration
```python
REDIS_CONFIG = {
    "host": "redis-cluster.internal",
    "port": 6379,
    "db": 0,
    "max_connections": 20,           # Service-specific pool size
    "socket_timeout": 0.1,           # Fast timeout for hot path
    "socket_connect_timeout": 0.5,   # Quick connection establishment
    "socket_keepalive": True,        # Maintain connections
    "socket_keepalive_options": {},
    "health_check_interval": 30,     # Connection health checks
    "retry_on_timeout": True,        # Automatic retry
    "decode_responses": True         # Auto-decode for Python strings
}
```

## Schema Evolution and Versioning

### 1. Backward Compatibility

#### Field Addition Strategy
```python
# Safe field addition
async def add_new_feature_field(symbol: str, field_name: str, value: float):
    # Check if field exists before using
    existing_value = await redis.hget(f"feat:{symbol}", field_name)
    
    if existing_value is None:
        await redis.hset(f"feat:{symbol}", field_name, str(value))
```

#### Schema Version Tracking
```redis
# Schema metadata
schema:version "2023-12-15"
schema:features:version "1.2.0"
schema:orderbook:version "1.1.0"
```

### 2. Migration Procedures

#### Rolling Schema Updates
```python
async def migrate_feature_schema_v1_to_v2():
    """Migrate feature schema while maintaining service availability"""
    
    # Add new fields with default values
    symbols = ["BTCUSDT"]
    
    for symbol in symbols:
        features = await redis.hgetall(f"feat:{symbol}")
        
        if features and "schema_version" not in features:
            # Add new fields
            updates = {
                "price_acceleration": "0.0",
                "volume_momentum": "0.0", 
                "schema_version": "2.0"
            }
            
            await redis.hset(f"feat:{symbol}", mapping=updates)
```

## Monitoring and Observability

### 1. Key Metrics

#### Redis Performance Metrics
```python
REDIS_METRICS = [
    "redis_connected_clients",
    "redis_used_memory_bytes",
    "redis_used_memory_rss_bytes", 
    "redis_keyspace_hits_total",
    "redis_keyspace_misses_total",
    "redis_commands_processed_total",
    "redis_commands_duration_seconds"
]
```

#### Application-Level Metrics
```python
APPLICATION_METRICS = [
    "redis_feature_read_duration_seconds",
    "redis_feature_age_seconds", 
    "redis_prediction_cache_hits_total",
    "redis_prediction_cache_misses_total",
    "redis_reanchor_operations_total",
    "redis_atomic_operations_total"
]
```

### 2. Health Monitoring

#### Key Existence Monitoring
```python
async def check_redis_health() -> dict:
    """Monitor Redis health and key availability"""
    
    health = {
        "status": "healthy",
        "timestamp": time.time(),
        "keys": {}
    }
    
    # Check critical keys
    critical_keys = [
        "ob:BTCUSDT",
        "tr:BTCUSDT:1s", 
        "tr:BTCUSDT:5s",
        "feat:BTCUSDT"
    ]
    
    for key in critical_keys:
        exists = await redis.exists(key)
        age = await get_key_age(key) if exists else None
        
        health["keys"][key] = {
            "exists": bool(exists),
            "age_seconds": age,
            "stale": age > 300 if age else True  # 5-minute staleness threshold
        }
    
    # Overall health assessment
    missing_keys = [k for k, v in health["keys"].items() if not v["exists"]]
    stale_keys = [k for k, v in health["keys"].items() if v.get("stale")]
    
    if missing_keys:
        health["status"] = "degraded"
        health["missing_keys"] = missing_keys
    
    if stale_keys:
        health["status"] = "degraded" 
        health["stale_keys"] = stale_keys
    
    return health
```

This Redis schema provides the foundation for sub-100ms Bitcoin price predictions through optimized hot state management, atomic operations, and systematic TTL strategies while maintaining zero-downtime reliability during re-anchoring operations.