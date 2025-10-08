# Bitcoin Pipeline Data Architecture

## Overview

The Bitcoin Pipeline implements a **tri-layer data architecture** designed for **10-second ahead price predictions** with **2-second update frequency**. The system uses hot path isolation, atomic re-anchoring, and hierarchical storage to achieve sub-100ms inference latency with zero-downtime reliability.

## Data Storage Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                           HOT LAYER (Redis)                         │
├─────────────────────────────────────────────────────────────────────┤
│ Purpose: Real-time inference state                                 │
│ Latency: <1ms reads                                               │
│ TTL: No TTL (order books) to 5min (trade stats)                   │
│ Size: ~100MB per symbol                                           │
│                                                                     │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│ │Order Books  │  │Trade Stats  │  │Features     │                 │
│ │(live state) │  │(rolling)    │  │(ML ready)   │                 │
│ └─────────────┘  └─────────────┘  └─────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────────┐
│                        HISTORICAL LAYER (S3)                       │
├─────────────────────────────────────────────────────────────────────┤
│ Purpose: Training data and historical analysis                     │
│ Latency: Seconds to minutes                                       │
│ Retention: Indefinite with lifecycle policies                     │
│ Size: TBs of historical market data                               │
│                                                                     │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│ │Bronze       │  │Silver       │  │Gold         │                 │
│ │(raw events) │  │(normalized) │  │(ML ready)   │                 │
│ └─────────────┘  └─────────────┘  └─────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────────┐
│                        CURATED LAYER (RDS)                         │
├─────────────────────────────────────────────────────────────────────┤
│ Purpose: Dashboards, audit logs, operational data                  │
│ Latency: 10-100ms                                                 │
│ Retention: 1 year for operational data                            │
│ Size: GBs of curated summaries                                    │
│                                                                     │
│ ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│ │Market       │  │Predictions  │  │Audit        │                 │
│ │Summaries    │  │History      │  │Logs         │                 │
│ └─────────────┘  └─────────────┘  └─────────────┘                 │
└─────────────────────────────────────────────────────────────────────┘
```

## Redis Hot Layer Specification

### Key Design Principles
1. **Hot Path Isolation**: Only Redis reads for inference
2. **Atomic Operations**: Use Redis transactions for consistency
3. **Memory Efficiency**: TTL management and data structure optimization
4. **Zero Downtime**: Atomic key swapping during re-anchoring

### Key Naming Conventions

```
Prefix   Purpose              TTL      Example
──────────────────────────────────────────────────────────────
ob:      Order book state     None     ob:BTCUSDT
tr:      Trade statistics     5min     tr:BTCUSDT:1s
feat:    Feature vectors      2min     feat:BTCUSDT
pred:    Latest prediction    10min    pred:BTCUSDT
reanchor: Re-anchor flag      1min     reanchor:BTCUSDT
```

### Order Book Schema (`ob:{symbol}`)

```redis
ob:BTCUSDT (HASH):
# Best bid/ask (critical for spreads)
├── best_bid: "45229.50"
├── best_ask: "45231.00"
├── spread: "1.50"
├── spread_bp: "3.32"        # Spread in basis points

# Top 10 bid levels
├── bid1_p: "45229.50", bid1_q: "1.5"
├── bid2_p: "45229.00", bid2_q: "2.1"
├── bid3_p: "45228.50", bid3_q: "0.8"
├── ...
├── bid10_p: "45225.00", bid10_q: "3.2"

# Top 10 ask levels  
├── ask1_p: "45231.00", ask1_q: "1.2"
├── ask2_p: "45231.50", ask2_q: "1.8"
├── ask3_p: "45232.00", ask3_q: "2.5"
├── ...
├── ask10_p: "45235.00", ask10_q: "1.9"

# Order book metrics
├── bid_value_sum: "1525840.75"   # Sum of bid1-10 values
├── ask_value_sum: "1526235.25"   # Sum of ask1-10 values
├── ob_imbalance: "0.031"         # (bid_val - ask_val) / (bid_val + ask_val)
├── weighted_mid: "45230.25"      # Volume-weighted mid price

# Metadata
├── last_update_id: "123456789"   # For sequence validation
├── ts_us: "1638360000123456"     # Microsecond precision
└── source: "sbe"                 # Data source
```

### Trade Statistics Schema (`tr:{symbol}:{window}`)

#### 1-Second Window (`tr:BTCUSDT:1s`)
```redis
tr:BTCUSDT:1s (HASH):           # TTL: 5 minutes
# Basic trade metrics
├── count: "15"                  # Number of trades
├── volume: "12.567"            # Total volume
├── notional: "567890.12"       # Total notional value
├── avg_price: "45230.25"       # Average trade price

# Buy/sell breakdown
├── buy_count: "9"              # Number of buy trades
├── sell_count: "6"             # Number of sell trades  
├── buy_volume: "8.234"         # Buy volume
├── sell_volume: "4.333"        # Sell volume
├── signed_volume: "3.901"      # buy_vol - sell_vol

# Price metrics
├── vwap: "45230.18"           # Volume-weighted average price
├── vwap_minus_mid: "0.05"     # VWAP deviation from mid
├── price_std: "0.23"          # Price standard deviation
├── price_range: "1.20"        # max_price - min_price

# Timing metrics
├── interarrival_mean: "0.067" # Mean seconds between trades
├── interarrival_var: "0.023"  # Variance of inter-arrival times
├── first_ts_us: "1638360000000000"
├── last_ts_us: "1638360001000000"

# Derived features
├── trade_intensity: "15.0"    # Trades per second
├── dollar_intensity: "567890.12" # Notional per second
└── avg_trade_size: "0.838"    # Average trade size
```

#### 5-Second Window (`tr:BTCUSDT:5s`)
```redis
tr:BTCUSDT:5s (HASH):           # TTL: 5 minutes
├── count: "75"
├── volume: "62.835"
├── notional: "2839450.60"
├── signed_volume: "8.745"
├── vwap: "45225.30"
├── vwap_minus_mid: "0.12"
├── trade_intensity: "15.0"
├── price_momentum: "0.0023"    # 5s price change rate
└── last_ts_us: "1638360005000000"
```

### Feature Vector Schema (`feat:{symbol}`)

```redis
feat:BTCUSDT (HASH):            # TTL: 2 minutes
# Price features
├── price: "45230.50"           # Latest trade price
├── mid_price: "45230.25"       # Order book mid price
├── ret_1s: "0.0002"           # 1-second return
├── ret_5s: "0.0015"           # 5-second return
├── ret_10s: "0.0032"          # 10-second return

# Volume features
├── volume_1s: "12.567"        # 1-second volume
├── volume_5s: "62.835"        # 5-second volume
├── vol_imbalance_1s: "0.031"  # 1s buy/sell imbalance
├── vol_imbalance_5s: "0.064"  # 5s buy/sell imbalance

# Order book features
├── spread_bp: "3.32"          # Spread in basis points
├── ob_imbalance: "0.031"      # Order book imbalance
├── bid_strength: "1525840.75" # Total bid value (L1-L10)
├── ask_strength: "1526235.25" # Total ask value (L1-L10)

# Trade flow features
├── trade_intensity_1s: "15.0" # Trades per second
├── trade_intensity_5s: "15.0" # 5s average
├── avg_trade_size_1s: "0.838" # Average trade size
├── dollar_volume_1s: "567890.12" # Dollar volume

# Technical indicators
├── vwap_dev_1s: "0.05"        # VWAP deviation from mid
├── vwap_dev_5s: "0.12"        # 5s VWAP deviation
├── price_volatility: "0.0023" # Rolling volatility
├── momentum: "0.0032"         # Price momentum

# Metadata
├── feature_ts: "1638360000"   # Feature computation timestamp
├── data_age_ms: "150"         # Age of underlying data
└── completeness: "1.0"        # Feature completeness ratio (0-1)
```

### Prediction Cache Schema (`pred:{symbol}`)

```redis
pred:BTCUSDT (HASH):            # TTL: 10 minutes
├── predicted_price: "45235.75" # Price 10 seconds ahead
├── current_price: "45230.50"   # Price at prediction time
├── confidence: "0.87"          # Model confidence (0-1)
├── prediction_ts: "1638360000" # When prediction was made
├── target_ts: "1638360010"     # Target time (10s ahead)
├── model_version: "v1.2.3"     # Model version used
├── latency_ms: "45"            # Inference latency
├── features_age_ms: "120"      # Age of input features
└── source: "redis"             # "redis" or "fallback"
```

## S3 Data Lake Specification

### Bronze Layer (Raw Data)

#### SBE Events
```
s3://bitcoin-data-lake/bronze/sbe/BTCUSDT/
├── trades/
│   └── year=2024/month=01/day=15/hour=14/
│       ├── trades_20240115_1400_001.parquet
│       ├── trades_20240115_1400_002.parquet
│       └── ...
├── depth/
│   └── year=2024/month=01/day=15/hour=14/
│       ├── depth_20240115_1400_001.parquet
│       └── ...
└── bestbidask/
    └── year=2024/month=01/day=15/hour=14/
        ├── bba_20240115_1400_001.parquet
        └── ...
```

#### Parquet Schema - SBE Trades
```python
{
    "symbol": "string",
    "event_ts": "int64",       # Exchange timestamp (microseconds)
    "ingest_ts": "int64",      # Our ingestion timestamp
    "trade_id": "int64",       # Trade ID
    "price": "double",         # Trade price
    "quantity": "double",      # Trade quantity
    "is_buyer_maker": "bool",  # Buyer is maker flag
    "sequence_id": "int64",    # SBE sequence ID
    "source": "string"         # Always "sbe"
}
```

#### REST API Data
```
s3://bitcoin-data-lake/bronze/rest/BTCUSDT/
├── aggTrades/
│   └── year=2024/month=01/day=15/
│       ├── aggTrades_20240115_001.parquet
│       └── ...
├── depth/
│   └── year=2024/month=01/day=15/
│       ├── depth_20240115_001.parquet
│       └── ...
└── klines/
    └── year=2024/month=01/day=15/
        ├── klines_1m_20240115_001.parquet
        └── ...
```

### Silver Layer (Normalized Data)

#### 1-Minute Market Bars
```
s3://bitcoin-data-lake/silver/bars_1m/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── bars_1m_20240115_001.parquet
    └── ...
```

#### Parquet Schema - 1-Minute Bars
```python
{
    "symbol": "string",
    "open_time": "int64",      # Bar open time (epoch ms)
    "close_time": "int64",     # Bar close time (epoch ms)
    "open": "double",          # Open price
    "high": "double",          # High price
    "low": "double",           # Low price
    "close": "double",         # Close price
    "volume": "double",        # Volume
    "notional": "double",      # Notional value
    "trade_count": "int32",    # Number of trades
    "buy_volume": "double",    # Buy volume
    "sell_volume": "double",   # Sell volume
    "vwap": "double",          # Volume-weighted average price
    "source": "string"         # "sbe" or "rest"
}
```

#### Order Book Snapshots (Hourly)
```
s3://bitcoin-data-lake/silver/snapshots/BTCUSDT/
└── year=2024/month=01/day=15/hour=14/
    ├── snapshot_20240115_1400.parquet
    └── ...
```

### Gold Layer (ML-Ready Data)

#### Feature Vectors (2-second intervals)
```
s3://bitcoin-data-lake/gold/features_2s/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── features_2s_20240115_001.parquet
    └── ...
```

#### Parquet Schema - Feature Vectors
```python
{
    "symbol": "string",
    "ts": "int64",             # Feature timestamp (epoch seconds)
    
    # Price features
    "price": "double",
    "mid_price": "double",
    "ret_1s": "double",
    "ret_5s": "double",
    "ret_10s": "double",
    
    # Volume features
    "volume_1s": "double",
    "volume_5s": "double", 
    "vol_imbalance_1s": "double",
    "vol_imbalance_5s": "double",
    
    # Order book features
    "spread_bp": "double",
    "ob_imbalance": "double",
    "bid_strength": "double",
    "ask_strength": "double",
    
    # Trade flow features
    "trade_intensity_1s": "double",
    "avg_trade_size_1s": "double",
    "dollar_volume_1s": "double",
    
    # Technical indicators
    "vwap_dev_1s": "double",
    "vwap_dev_5s": "double",
    "price_volatility": "double",
    "momentum": "double",
    
    # Data quality
    "completeness": "double",  # 0.0 - 1.0
    "data_age_ms": "int32"     # Age of underlying data
}
```

#### Labels (10-second ahead targets)
```
s3://bitcoin-data-lake/gold/labels_10s/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── labels_10s_20240115_001.parquet
    └── ...
```

#### Parquet Schema - Labels
```python
{
    "symbol": "string",
    "feature_ts": "int64",     # Feature timestamp
    "target_ts": "int64",      # Target timestamp (feature_ts + 10s)
    "current_price": "double", # Price at feature_ts
    "target_price": "double",  # Price at target_ts
    "price_change": "double",  # target_price - current_price
    "return_10s": "double",    # log(target_price / current_price)
    "direction": "int8",       # 1 if up, -1 if down, 0 if flat
    "volatility": "double",    # Price volatility during 10s window
    "valid": "bool"            # Whether label is valid (no gaps)
}
```

## RDS Curated Layer Specification

### Database Schema

#### Table: `minute_bars`
```sql
CREATE TABLE minute_bars (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    open_time BIGINT NOT NULL,
    close_time BIGINT NOT NULL,
    open_price DECIMAL(20,8) NOT NULL,
    high_price DECIMAL(20,8) NOT NULL,
    low_price DECIMAL(20,8) NOT NULL,
    close_price DECIMAL(20,8) NOT NULL,
    volume DECIMAL(20,8) NOT NULL,
    notional DECIMAL(20,8) NOT NULL,
    trade_count INTEGER NOT NULL,
    buy_volume DECIMAL(20,8),
    sell_volume DECIMAL(20,8),
    vwap DECIMAL(20,8),
    source VARCHAR(10) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    
    UNIQUE(symbol, open_time),
    INDEX idx_symbol_time (symbol, open_time),
    INDEX idx_close_time (close_time)
) PARTITION BY RANGE (open_time);
```

#### Table: `predictions_log`
```sql
CREATE TABLE predictions_log (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    prediction_ts BIGINT NOT NULL,
    target_ts BIGINT NOT NULL,
    current_price DECIMAL(20,8) NOT NULL,
    predicted_price DECIMAL(20,8) NOT NULL,
    confidence DECIMAL(8,6) NOT NULL,
    model_version VARCHAR(50) NOT NULL,
    latency_ms INTEGER NOT NULL,
    features_age_ms INTEGER NOT NULL,
    source VARCHAR(20) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    
    # Add actual outcome when available
    actual_price DECIMAL(20,8),
    prediction_error DECIMAL(20,8),
    directional_correct BOOLEAN,
    
    INDEX idx_symbol_pred_ts (symbol, prediction_ts),
    INDEX idx_target_ts (target_ts),
    INDEX idx_model_version (model_version)
) PARTITION BY RANGE (prediction_ts);
```

#### Table: `latest_market_state`
```sql
CREATE TABLE latest_market_state (
    symbol VARCHAR(20) PRIMARY KEY,
    price DECIMAL(20,8) NOT NULL,
    bid_price DECIMAL(20,8),
    ask_price DECIMAL(20,8),
    spread DECIMAL(20,8),
    volume_1s DECIMAL(20,8),
    volume_5s DECIMAL(20,8),
    trade_count_1s INTEGER,
    trade_count_5s INTEGER,
    vwap_1s DECIMAL(20,8),
    vwap_5s DECIMAL(20,8),
    last_trade_ts BIGINT NOT NULL,
    last_update_ts BIGINT NOT NULL,
    data_source VARCHAR(20) NOT NULL,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

#### Table: `service_health_log`
```sql
CREATE TABLE service_health_log (
    id BIGSERIAL PRIMARY KEY,
    service_name VARCHAR(50) NOT NULL,
    health_status VARCHAR(20) NOT NULL,
    latency_p50_ms DECIMAL(10,2),
    latency_p95_ms DECIMAL(10,2),
    latency_p99_ms DECIMAL(10,2),
    error_rate DECIMAL(8,6),
    redis_hit_rate DECIMAL(8,6),
    features_age_ms INTEGER,
    sbe_events_per_sec DECIMAL(10,2),
    predictions_per_min INTEGER,
    checktime TIMESTAMP NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    
    INDEX idx_service_checktime (service_name, checktime),
    INDEX idx_checktime (checktime)
) PARTITION BY RANGE (EXTRACT(EPOCH FROM checktime));
```

## Data Flow Operations

### Hot Path Data Flow (Real-time)

```python
# SBE Event → Redis Update
async def process_sbe_trade(trade_event):
    # 1. Update order book if needed
    if trade_event.affects_book:
        await update_order_book(trade_event)
    
    # 2. Update trade statistics
    await update_trade_stats(trade_event, windows=['1s', '5s'])
    
    # 3. Recompute features if enough updates
    if should_update_features():
        await compute_and_cache_features()

# Inference reads (every 2 seconds)
async def generate_prediction():
    features = await redis.hgetall('feat:BTCUSDT')
    if is_fresh(features):
        prediction = model.predict(features)
        await cache_prediction(prediction)
        return prediction
```

### Reliability Path Data Flow (Re-anchoring)

```python
# Atomic re-anchoring procedure
async def reanchor_symbol(symbol):
    # 1. Set re-anchor flag
    await redis.set(f'reanchor:{symbol}', '1', ex=300)
    
    # 2. Fetch fresh data from REST
    depth = await binance.get_depth(symbol)
    trades = await binance.get_recent_trades(symbol)
    
    # 3. Build new state in temp keys
    await build_temp_order_book(f'ob:new:{symbol}', depth)
    await build_temp_trade_stats(f'tr:new:{symbol}', trades)
    await build_temp_features(f'feat:new:{symbol}')
    
    # 4. Atomic swap
    pipeline = redis.pipeline()
    pipeline.rename(f'ob:new:{symbol}', f'ob:{symbol}')
    pipeline.rename(f'tr:new:{symbol}:1s', f'tr:{symbol}:1s')
    pipeline.rename(f'tr:new:{symbol}:5s', f'tr:{symbol}:5s')
    pipeline.rename(f'feat:new:{symbol}', f'feat:{symbol}')
    pipeline.delete(f'reanchor:{symbol}')
    await pipeline.execute()
```

### Training Path Data Flow (Batch)

```python
# S3 ETL Pipeline
def process_bronze_to_silver():
    # Daily batch job
    # 1. Read bronze Parquet files
    # 2. Normalize and validate data
    # 3. Generate 1-minute bars
    # 4. Create order book snapshots
    # 5. Write to silver layer

def process_silver_to_gold():
    # Daily feature engineering
    # 1. Read silver normalized data
    # 2. Compute feature vectors (2s intervals)
    # 3. Generate labels (10s ahead)
    # 4. Write ML-ready datasets to gold layer

def train_model():
    # Weekly model training
    # 1. Read gold layer training data
    # 2. Feature engineering and validation
    # 3. Train lightweight MLP
    # 4. Export ONNX model
    # 5. Deploy to inference service
```

## Data Quality and Validation

### Real-time Validation
- **Sequence ID Continuity**: Monitor SBE sequence IDs for gaps
- **Timestamp Validation**: Ensure timestamps are monotonic and reasonable
- **Price Validation**: Check for outliers and impossible price movements
- **Volume Validation**: Validate trade sizes and volume calculations

### Feature Quality Metrics
- **Completeness**: Percentage of features successfully computed
- **Freshness**: Age of underlying data used for features
- **Consistency**: Cross-validation between SBE and REST data
- **Accuracy**: Validation against known market conditions

### Data Retention Policies

```yaml
Redis:
  order_books: no_ttl        # Always live
  trade_stats: 5_minutes     # Rolling windows
  features: 2_minutes        # ML inference
  predictions: 10_minutes    # Recent predictions

S3:
  bronze: 7_years           # Raw data retention
  silver: 5_years           # Normalized data
  gold: 3_years             # ML datasets

RDS:
  minute_bars: 2_years      # Market summary data
  predictions_log: 1_year   # Prediction audit
  health_logs: 90_days      # Operational metrics
```

This comprehensive data pipeline supports real-time inference with <100ms latency while maintaining data integrity and enabling continuous model improvement through the training pipeline.