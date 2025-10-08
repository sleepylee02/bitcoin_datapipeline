# Bitcoin Aggregator Service - Redis State Management & Atomic Operations

## Overview

The Bitcoin Aggregator Service is the **core real-time processor** that maintains Redis hot state for the 10-second ahead Bitcoin price prediction pipeline. It consumes SBE events from Kinesis streams, computes rolling features every 2 seconds, and performs atomic operations during re-anchoring to ensure **zero-downtime** reliability.

## Architecture Philosophy

- **Hot State Maintenance**: Real-time Redis updates for sub-100ms inference
- **Atomic Operations**: Transaction-based updates during re-anchoring
- **Feature Pipeline**: 2-second feature computation for prediction accuracy
- **Zero Compromise**: Never block inference reads during processing

## Core Responsibilities

```
┌─────────────────────────────────────────────────────────────────┐
│                    AGGREGATOR SERVICE ROLE                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Kinesis Streams ──► Stream Processing ──► Redis Hot State     │
│  (SBE events)     │  (real-time)       │  (order books,       │
│                   │                    │   trade stats,       │
│                   │                    │   features)          │
│                   ▼                    ▼                       │
│             ┌──────────────┐     ┌──────────────┐              │
│             │Rolling Stats │     │Feature Vector│              │
│             │(1s, 5s wins) │     │(every 2s)    │              │
│             └──────────────┘     └──────────────┘              │
│                   │                    │                       │
│                   ▼                    ▼                       │
│             ┌──────────────┐     ┌──────────────┐              │
│             │Atomic        │     │Inference     │              │
│             │Re-anchor     │     │Ready State   │              │
│             │Support       │     │(<100ms reads)│              │
│             └──────────────┘     └──────────────┘              │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export REDIS_HOST="localhost"
export REDIS_PORT="6379"
export AWS_REGION="us-east-1"
```

### Local Development with Docker Compose

1. **Start Infrastructure**:
```bash
cd ../../  # Project root
docker-compose up localstack redis -d
```

2. **Run Aggregator Service**:
```bash
CONFIG_FILE=config/local.yaml python src/main.py
```

3. **Check Health**:
```bash
curl http://localhost:8082/health
```

### Production Deployment

```bash
# Build and deploy
docker build -t bitcoin-aggregator .

docker run -d --name aggregator \
  -p 8082:8082 \
  -e CONFIG_FILE=config/prod.yaml \
  -e REDIS_HOST=${REDIS_HOST} \
  -e AWS_REGION=${AWS_REGION} \
  bitcoin-aggregator
```

## Configuration

### Aggregator Configuration (`config/aggregator.yaml`)
```yaml
service_name: "bitcoin-aggregator"

aws:
  region: "us-east-1"
  kinesis:
    streams:
      trade: "market-sbe-trade"
      bestbidask: "market-sbe-bestbidask"
      depth: "market-sbe-depth"
    consumer_config:
      shard_iterator_type: "LATEST"
      max_records_per_poll: 1000
      poll_interval_ms: 100

redis:
  host: "localhost"
  port: 6379
  cluster_mode: false
  connection_pool_size: 20
  max_connections: 50
  socket_timeout_seconds: 1
  socket_connect_timeout_seconds: 1

processing:
  feature_update_interval_seconds: 2
  trade_window_sizes: [1, 5]  # seconds
  order_book_levels: 10
  batch_size: 500
  flush_interval_ms: 100

health:
  port: 8082
  host: "0.0.0.0"

metrics:
  enable_prometheus: true
  prometheus_port: 9091
```

## Data Processing Pipeline

### 1. Kinesis Stream Consumption

#### Stream Types and Processing
```python
STREAM_PROCESSORS = {
    "market-sbe-trade": TradeProcessor,
    "market-sbe-bestbidask": BestBidAskProcessor, 
    "market-sbe-depth": DepthProcessor
}
```

#### Trade Event Processing
```python
async def process_trade_event(trade_event: dict):
    """Process individual trade event from SBE stream"""
    
    # 1. Update current price
    await redis.hset(f"ob:{symbol}", "last_trade_price", trade_event["price"])
    
    # 2. Update rolling trade statistics
    await update_trade_statistics(trade_event, windows=[1, 5])
    
    # 3. Trigger feature computation if enough updates
    if should_update_features():
        await compute_and_cache_features(symbol)
```

#### Best Bid/Ask Processing
```python
async def process_bestbidask_event(bba_event: dict):
    """Process best bid/ask updates"""
    
    # Atomic order book update
    pipeline = redis.pipeline()
    pipeline.hset(f"ob:{symbol}", "best_bid", bba_event["bid_price"])
    pipeline.hset(f"ob:{symbol}", "best_ask", bba_event["ask_price"])
    pipeline.hset(f"ob:{symbol}", "spread", 
                 bba_event["ask_price"] - bba_event["bid_price"])
    pipeline.hset(f"ob:{symbol}", "ts_us", bba_event["timestamp"])
    await pipeline.execute()
```

#### Depth Update Processing
```python
async def process_depth_event(depth_event: dict):
    """Process order book depth updates"""
    
    # Maintain top 10 levels
    for i, (price, qty) in enumerate(depth_event["bids"][:10], 1):
        await redis.hset(f"ob:{symbol}", f"bid{i}_p", price)
        await redis.hset(f"ob:{symbol}", f"bid{i}_q", qty)
    
    for i, (price, qty) in enumerate(depth_event["asks"][:10], 1):
        await redis.hset(f"ob:{symbol}", f"ask{i}_p", price)
        await redis.hset(f"ob:{symbol}", f"ask{i}_q", qty)
    
    # Compute order book metrics
    await compute_orderbook_metrics(symbol)
```

### 2. Rolling Trade Statistics

#### 1-Second Window Statistics (`tr:BTCUSDT:1s`)
```python
async def update_trade_statistics_1s(trades: List[dict], symbol: str):
    """Update 1-second rolling trade statistics"""
    
    stats = {
        "count": len(trades),
        "volume": sum(t["quantity"] for t in trades),
        "notional": sum(t["price"] * t["quantity"] for t in trades),
        "buy_volume": sum(t["quantity"] for t in trades if not t["is_buyer_maker"]),
        "sell_volume": sum(t["quantity"] for t in trades if t["is_buyer_maker"]),
        "vwap": calculate_vwap(trades),
        "price_std": calculate_price_std(trades),
        "trade_intensity": len(trades) / 1.0,  # trades per second
        "avg_trade_size": sum(t["quantity"] for t in trades) / len(trades),
        "last_ts_us": trades[-1]["timestamp"]
    }
    
    # Derived metrics
    stats["signed_volume"] = stats["buy_volume"] - stats["sell_volume"]
    mid_price = await get_mid_price(symbol)
    stats["vwap_minus_mid"] = stats["vwap"] - mid_price
    
    # Atomic update with TTL
    await redis.hset(f"tr:{symbol}:1s", mapping=stats)
    await redis.expire(f"tr:{symbol}:1s", 300)  # 5-minute TTL
```

#### 5-Second Window Statistics (`tr:BTCUSDT:5s`)
```python
async def update_trade_statistics_5s(trades: List[dict], symbol: str):
    """Update 5-second rolling trade statistics"""
    
    # Similar structure but 5-second aggregation
    stats = calculate_rolling_stats(trades, window_seconds=5)
    
    # Additional 5s metrics
    stats["price_momentum"] = calculate_price_momentum(trades)
    stats["volume_acceleration"] = calculate_volume_acceleration(trades)
    
    await redis.hset(f"tr:{symbol}:5s", mapping=stats)
    await redis.expire(f"tr:{symbol}:5s", 300)
```

### 3. Feature Vector Computation

#### Feature Pipeline (Every 2 seconds)
```python
async def compute_and_cache_features(symbol: str):
    """Compute ML-ready feature vector from Redis state"""
    
    # 1. Gather all required data
    order_book = await redis.hgetall(f"ob:{symbol}")
    trade_stats_1s = await redis.hgetall(f"tr:{symbol}:1s")
    trade_stats_5s = await redis.hgetall(f"tr:{symbol}:5s")
    
    # 2. Compute derived features
    features = {
        # Price features
        "price": float(order_book.get("last_trade_price", 0)),
        "mid_price": (float(order_book["best_bid"]) + float(order_book["best_ask"])) / 2,
        "ret_1s": calculate_return(symbol, window=1),
        "ret_5s": calculate_return(symbol, window=5),
        "ret_10s": calculate_return(symbol, window=10),
        
        # Volume features
        "volume_1s": float(trade_stats_1s.get("volume", 0)),
        "volume_5s": float(trade_stats_5s.get("volume", 0)),
        "vol_imbalance_1s": float(trade_stats_1s.get("signed_volume", 0)) / 
                           float(trade_stats_1s.get("volume", 1)),
        "vol_imbalance_5s": float(trade_stats_5s.get("signed_volume", 0)) / 
                           float(trade_stats_5s.get("volume", 1)),
        
        # Order book features
        "spread_bp": (float(order_book["best_ask"]) - float(order_book["best_bid"])) /
                     float(order_book["best_bid"]) * 10000,
        "ob_imbalance": calculate_orderbook_imbalance(order_book),
        "bid_strength": calculate_bid_strength(order_book),
        "ask_strength": calculate_ask_strength(order_book),
        
        # Trade flow features
        "trade_intensity_1s": float(trade_stats_1s.get("trade_intensity", 0)),
        "avg_trade_size_1s": float(trade_stats_1s.get("avg_trade_size", 0)),
        "dollar_volume_1s": float(trade_stats_1s.get("notional", 0)),
        
        # Technical indicators
        "vwap_dev_1s": float(trade_stats_1s.get("vwap_minus_mid", 0)),
        "vwap_dev_5s": float(trade_stats_5s.get("vwap_minus_mid", 0)),
        "price_volatility": float(trade_stats_1s.get("price_std", 0)),
        "momentum": float(trade_stats_5s.get("price_momentum", 0)),
        
        # Metadata
        "feature_ts": int(time.time()),
        "data_age_ms": calculate_data_age(order_book, trade_stats_1s),
        "completeness": calculate_feature_completeness()
    }
    
    # 3. Atomic feature update with TTL
    await redis.hset(f"feat:{symbol}", mapping=features)
    await redis.expire(f"feat:{symbol}", 120)  # 2-minute TTL
```

## Atomic Re-anchoring Support

### 1. Re-anchor Detection and Coordination

#### Re-anchor Flag Management
```python
async def handle_reanchor_request(symbol: str):
    """Handle atomic re-anchoring request from REST service"""
    
    # Check if re-anchor is already in progress
    if await redis.exists(f"reanchor:{symbol}"):
        logger.warning(f"Re-anchor already in progress for {symbol}")
        return False
    
    # Set re-anchor flag with timeout
    await redis.set(f"reanchor:{symbol}", "1", ex=300)  # 5-minute timeout
    logger.info(f"Re-anchor flag set for {symbol}")
    
    # Pause normal processing during re-anchor
    return True
```

### 2. Temporary Key Building

#### Build New State in Temporary Keys
```python
async def build_temporary_state(symbol: str, rest_data: dict):
    """Build new Redis state in temporary keys from REST data"""
    
    # 1. Build temporary order book
    depth_data = rest_data["depth"]
    temp_ob = {
        "best_bid": str(depth_data["bids"][0][0]),
        "best_ask": str(depth_data["asks"][0][0]),
        "spread": str(float(depth_data["asks"][0][0]) - float(depth_data["bids"][0][0])),
        "ts_us": str(int(time.time() * 1_000_000))
    }
    
    # Add top 10 levels
    for i, (price, qty) in enumerate(depth_data["bids"][:10], 1):
        temp_ob[f"bid{i}_p"] = price
        temp_ob[f"bid{i}_q"] = qty
    
    for i, (price, qty) in enumerate(depth_data["asks"][:10], 1):
        temp_ob[f"ask{i}_p"] = price
        temp_ob[f"ask{i}_q"] = qty
    
    await redis.hset(f"ob:new:{symbol}", mapping=temp_ob)
    
    # 2. Build temporary trade statistics
    trades_data = rest_data["trades"]
    temp_stats_1s = calculate_trade_stats_from_rest(trades_data, window=1)
    temp_stats_5s = calculate_trade_stats_from_rest(trades_data, window=5)
    
    await redis.hset(f"tr:new:{symbol}:1s", mapping=temp_stats_1s)
    await redis.hset(f"tr:new:{symbol}:5s", mapping=temp_stats_5s)
    
    # 3. Build temporary features
    temp_features = await compute_features_from_temp_state(symbol)
    await redis.hset(f"feat:new:{symbol}", mapping=temp_features)
```

### 3. Atomic Key Swapping

#### Coordinated Atomic Swap
```python
async def perform_atomic_swap(symbol: str):
    """Perform atomic Redis key swap for zero-downtime re-anchoring"""
    
    try:
        # Start Redis transaction
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
        
        # Execute all operations atomically
        results = await pipeline.execute()
        
        logger.info(f"Atomic swap completed successfully for {symbol}")
        return True
        
    except Exception as e:
        logger.error(f"Atomic swap failed for {symbol}: {e}")
        
        # Cleanup temporary keys on failure
        await cleanup_temp_keys(symbol)
        await redis.delete(f"reanchor:{symbol}")
        
        return False

async def cleanup_temp_keys(symbol: str):
    """Clean up temporary keys if atomic swap fails"""
    temp_keys = [
        f"ob:new:{symbol}",
        f"tr:new:{symbol}:1s", 
        f"tr:new:{symbol}:5s",
        f"feat:new:{symbol}"
    ]
    
    for key in temp_keys:
        await redis.delete(key)
```

## Performance Optimizations

### 1. Batch Processing

#### Kinesis Record Batching
```python
class KinesisConsumer:
    def __init__(self, batch_size=500, flush_interval_ms=100):
        self.batch_size = batch_size
        self.flush_interval_ms = flush_interval_ms
        self.batch_buffer = []
        
    async def process_records_batch(self, records: List[dict]):
        """Process Kinesis records in batches for efficiency"""
        
        trades_batch = []
        depth_batch = []
        bba_batch = []
        
        # Group by message type
        for record in records:
            msg_type = record.get("message_type")
            if msg_type == "trade":
                trades_batch.append(record)
            elif msg_type == "depth":
                depth_batch.append(record)
            elif msg_type == "bestbidask":
                bba_batch.append(record)
        
        # Process batches in parallel
        await asyncio.gather(
            self.process_trades_batch(trades_batch),
            self.process_depth_batch(depth_batch),
            self.process_bba_batch(bba_batch)
        )
```

### 2. Redis Connection Optimization

#### Connection Pooling
```python
class RedisManager:
    def __init__(self, config):
        self.pool = redis.ConnectionPool(
            host=config.redis.host,
            port=config.redis.port,
            max_connections=config.redis.max_connections,
            socket_timeout=config.redis.socket_timeout_seconds,
            socket_connect_timeout=config.redis.socket_connect_timeout_seconds,
            retry_on_timeout=True
        )
        self.redis = redis.Redis(connection_pool=self.pool)
    
    async def pipeline_operations(self, operations: List[callable]):
        """Execute multiple Redis operations in pipeline for efficiency"""
        pipeline = self.redis.pipeline()
        
        for operation in operations:
            operation(pipeline)
        
        return await pipeline.execute()
```

### 3. Memory Management

#### TTL Strategy
```yaml
Redis Key TTL Strategy:
├── Order Books (ob:*): No TTL (always live state)
├── Trade Stats (tr:*): 5 minutes (rolling windows)
├── Features (feat:*): 2 minutes (inference freshness)
├── Temp Keys (*.new.*): 10 minutes (re-anchor safety)
└── Re-anchor Flags: 5 minutes (prevent deadlock)
```

## Health Monitoring

### Health Check Endpoint
```bash
GET /health
{
  "status": "healthy",
  "service": "bitcoin-aggregator",
  "components": {
    "kinesis_consumers": {
      "trade_stream": {
        "status": "consuming",
        "records_per_second": 125.5,
        "lag_seconds": 0.5,
        "last_processed": "2024-01-15T14:30:00Z"
      },
      "depth_stream": {
        "status": "consuming", 
        "records_per_second": 45.2,
        "lag_seconds": 0.3
      },
      "bestbidask_stream": {
        "status": "consuming",
        "records_per_second": 15.8,
        "lag_seconds": 0.2
      }
    },
    "redis_cluster": {
      "status": "connected",
      "connection_pool_usage": 0.65,
      "operations_per_second": 2500,
      "avg_latency_ms": 0.8
    },
    "feature_pipeline": {
      "status": "active",
      "last_feature_update": "2024-01-15T14:29:58Z",
      "features_per_minute": 30,
      "feature_completeness": 0.98
    },
    "reanchor_system": {
      "status": "ready",
      "active_reanchors": 0,
      "last_reanchor": "2024-01-15T12:15:30Z",
      "reanchor_success_rate": 1.0
    }
  }
}
```

## Performance Metrics

### Key Metrics
- `aggregator_kinesis_records_processed_total` - Kinesis records processed
- `aggregator_redis_operations_total` - Redis operations executed
- `aggregator_feature_updates_total` - Feature vector updates
- `aggregator_feature_computation_duration_seconds` - Feature computation latency
- `aggregator_reanchor_operations_total` - Re-anchor operations performed
- `aggregator_reanchor_duration_seconds` - Re-anchor operation duration

### Performance Targets
```
Component                    Target       P99 Max
──────────────────────────────────────────────────
Redis Write Operations      < 1ms        < 5ms
Feature Computation         < 10ms       < 20ms
Kinesis Record Processing   < 5ms        < 15ms
Atomic Re-anchor Duration   < 30s        < 60s
Memory Usage                < 2GB        < 4GB
```

## Error Handling

### 1. Kinesis Stream Errors
```python
async def handle_kinesis_error(stream_name: str, error: Exception):
    """Handle Kinesis stream processing errors"""
    
    if isinstance(error, ProvisionedThroughputExceededException):
        # Implement exponential backoff
        await asyncio.sleep(min(2 ** retry_count, 60))
        
    elif isinstance(error, ExpiredIteratorException):
        # Reset shard iterator
        await reset_shard_iterator(stream_name)
        
    else:
        logger.error(f"Kinesis error for {stream_name}: {error}")
        # Continue processing other streams
```

### 2. Redis Connection Errors
```python
async def handle_redis_error(operation: str, error: Exception):
    """Handle Redis connection and operation errors"""
    
    if isinstance(error, redis.ConnectionError):
        # Attempt reconnection
        await reconnect_redis()
        
    elif isinstance(error, redis.TimeoutError):
        # Log timeout but continue
        logger.warning(f"Redis timeout for {operation}")
        
    else:
        # Alert for other Redis errors
        await alert_ops_team("REDIS_ERROR", operation=operation, error=str(error))
```

### 3. Feature Computation Errors
```python
async def handle_feature_error(symbol: str, error: Exception):
    """Handle feature computation errors gracefully"""
    
    try:
        # Use last known good features
        await copy_last_known_features(symbol)
        
        # Reduce feature completeness score
        await redis.hset(f"feat:{symbol}", "completeness", "0.5")
        
    except Exception:
        # Set degraded feature state
        await set_degraded_features(symbol)
```

## Testing Strategy

### Unit Tests
```bash
# Test Redis operations
pytest tests/unit/test_redis_operations.py

# Test feature computation
pytest tests/unit/test_feature_computation.py

# Test atomic operations
pytest tests/unit/test_atomic_operations.py
```

### Integration Tests
```bash
# Test Kinesis → Redis pipeline
pytest tests/integration/test_kinesis_pipeline.py

# Test atomic re-anchoring
pytest tests/integration/test_reanchor_flow.py

# Test full aggregation pipeline
pytest tests/integration/test_full_pipeline.py
```

### Performance Tests
```bash
# Test feature computation latency (<20ms requirement)
pytest tests/performance/test_feature_latency.py

# Test atomic re-anchor speed (<60s requirement)
pytest tests/performance/test_reanchor_speed.py

# Test Redis operation throughput
pytest tests/performance/test_redis_throughput.py
```

## Development Guidelines

### Key Implementation Rules
1. **Atomic Operations**: Always use Redis pipelines for multi-key updates
2. **TTL Management**: Set appropriate TTLs to prevent memory leaks
3. **Error Isolation**: One stream error should not affect others
4. **Zero Downtime**: Re-anchoring must never clear live state
5. **Feature Freshness**: Update features every 2 seconds maximum

### Code Quality Standards
- Type hints for all function parameters and returns
- Comprehensive error handling with specific exception types
- Prometheus metrics for all critical operations
- Structured logging with correlation IDs
- Unit test coverage >90%

This aggregator service ensures reliable Redis state management with atomic operations, enabling sub-100ms inference latency while maintaining zero-downtime reliability during gap recovery operations.