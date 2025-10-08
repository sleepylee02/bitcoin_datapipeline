# S3 Data Lake Schema Documentation

## Overview

The S3 Data Lake implements a **tri-layer architecture** (Bronze → Silver → Gold) for the Bitcoin price prediction pipeline. It stores historical data for model training, provides data lineage, and enables comprehensive analysis while supporting the 10-second ahead prediction system.

## Data Lake Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    S3 DATA LAKE LAYERS                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   BRONZE    │    │   SILVER    │    │    GOLD     │         │
│  │ (Raw Data)  │───▶│(Normalized) │───▶│(ML Ready)   │         │
│  │             │    │             │    │             │         │
│  │• SBE Events │    │• 1min Bars  │    │• Features   │         │
│  │• REST API   │    │• Snapshots  │    │• Labels     │         │
│  │• Original   │    │• Validated  │    │• Training   │         │
│  │  Format     │    │• Cleaned    │    │  Datasets   │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
│        │                   │                   │               │
│        ▼                   ▼                   ▼               │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │Ingestor     │    │ETL Pipeline │    │Trainer      │         │
│  │Services     │    │(Daily Batch)│    │Service      │         │
│  └─────────────┘    └─────────────┘    └─────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

## S3 Bucket Structure

### Root Organization
```
s3://bitcoin-data-lake/
├── bronze/                   # Raw ingested data
│   ├── sbe/                 # SBE stream data
│   └── rest/                # REST API data
├── silver/                  # Normalized data
│   ├── bars_1m/            # 1-minute candlestick bars
│   ├── snapshots/          # Order book snapshots
│   └── trades_agg/         # Aggregated trade data
├── gold/                    # ML-ready datasets
│   ├── features_2s/        # Feature vectors (2s intervals)
│   ├── labels_10s/         # Labels (10s ahead targets)
│   └── training_sets/      # Complete training datasets
├── models/                  # Trained model artifacts
│   ├── btc_predictor/      # Bitcoin prediction models
│   └── experimental/       # Research models
├── config/                  # Configuration and metadata
│   ├── schemas/            # Schema definitions
│   └── pipelines/          # ETL pipeline configs
└── temp/                   # Temporary processing data
    ├── staging/            # Staging area for ETL
    └── checkpoints/        # Processing checkpoints
```

## Bronze Layer (Raw Data)

### Purpose
- **Immutable Storage**: Preserve original data for auditing and reprocessing
- **Data Lineage**: Track data sources and ingestion timestamps
- **Disaster Recovery**: Source of truth for rebuilding downstream layers
- **Compliance**: Maintain raw records for regulatory requirements

### 1. SBE Stream Data

#### Directory Structure
```
s3://bitcoin-data-lake/bronze/sbe/BTCUSDT/
├── trades/
│   └── year=2024/month=01/day=15/hour=14/
│       ├── trades_20240115_1400_001.parquet
│       ├── trades_20240115_1400_002.parquet
│       └── trades_20240115_1400_003.parquet
├── depth/
│   └── year=2024/month=01/day=15/hour=14/
│       ├── depth_20240115_1400_001.parquet
│       └── depth_20240115_1400_002.parquet
└── bestbidask/
    └── year=2024/month=01/day=15/hour=14/
        ├── bba_20240115_1400_001.parquet
        └── bba_20240115_1400_002.parquet
```

#### Partitioning Strategy
- **Time-based partitioning**: year/month/day/hour for optimal query performance
- **File size**: ~100MB per file for efficient processing
- **Naming convention**: `{type}_{YYYYMMDD}_{HHMM}_{sequence}.parquet`

#### SBE Trade Events Schema
```json
{
  "type": "record",
  "name": "SBETrade",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "event_ts", "type": "long", "doc": "Exchange timestamp (microseconds)"},
    {"name": "ingest_ts", "type": "long", "doc": "Ingestion timestamp (microseconds)"},
    {"name": "trade_id", "type": "long"},
    {"name": "price", "type": "double"},
    {"name": "quantity", "type": "double"},
    {"name": "is_buyer_maker", "type": "boolean"},
    {"name": "sequence_id", "type": "long", "doc": "SBE sequence for gap detection"},
    {"name": "source", "type": "string", "default": "sbe"},
    {"name": "partition_date", "type": "string", "doc": "YYYY-MM-DD for partitioning"},
    {"name": "partition_hour", "type": "int", "doc": "0-23 for hourly partitioning"}
  ]
}
```

#### Example Parquet Records
```python
# trades_20240115_1400_001.parquet content sample
[
    {
        "symbol": "BTCUSDT",
        "event_ts": 1705329600123456,
        "ingest_ts": 1705329600125000,
        "trade_id": 123456789,
        "price": 45230.50,
        "quantity": 0.1567,
        "is_buyer_maker": False,
        "sequence_id": 987654321,
        "source": "sbe",
        "partition_date": "2024-01-15",
        "partition_hour": 14
    },
    # ... more records
]
```

#### SBE Best Bid/Ask Schema
```json
{
  "type": "record", 
  "name": "SBEBestBidAsk",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "event_ts", "type": "long"},
    {"name": "ingest_ts", "type": "long"},
    {"name": "bid_price", "type": "double"},
    {"name": "bid_quantity", "type": "double"},
    {"name": "ask_price", "type": "double"},
    {"name": "ask_quantity", "type": "double"},
    {"name": "sequence_id", "type": "long"},
    {"name": "source", "type": "string", "default": "sbe"},
    {"name": "partition_date", "type": "string"},
    {"name": "partition_hour", "type": "int"}
  ]
}
```

#### SBE Depth Updates Schema
```json
{
  "type": "record",
  "name": "SBEDepthUpdate", 
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "event_ts", "type": "long"},
    {"name": "ingest_ts", "type": "long"},
    {"name": "first_update_id", "type": "long"},
    {"name": "final_update_id", "type": "long"},
    {"name": "bids", "type": {
      "type": "array",
      "items": {
        "type": "record",
        "fields": [
          {"name": "price", "type": "double"},
          {"name": "quantity", "type": "double"}
        ]
      }
    }},
    {"name": "asks", "type": {
      "type": "array", 
      "items": {
        "type": "record",
        "fields": [
          {"name": "price", "type": "double"},
          {"name": "quantity", "type": "double"}
        ]
      }
    }},
    {"name": "source", "type": "string", "default": "sbe"},
    {"name": "partition_date", "type": "string"},
    {"name": "partition_hour", "type": "int"}
  ]
}
```

### 2. REST API Data

#### Directory Structure
```
s3://bitcoin-data-lake/bronze/rest/BTCUSDT/
├── aggTrades/
│   └── year=2024/month=01/day=15/
│       ├── aggTrades_20240115_001.parquet
│       └── aggTrades_20240115_002.parquet
├── depth/
│   └── year=2024/month=01/day=15/
│       ├── depth_20240115_001.parquet
│       └── depth_20240115_002.parquet
└── klines/
    └── year=2024/month=01/day=15/
        ├── klines_1m_20240115_001.parquet
        └── klines_1m_20240115_002.parquet
```

#### REST Aggregate Trades Schema
```json
{
  "type": "record",
  "name": "RESTAggTrade",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "agg_trade_id", "type": "long"},
    {"name": "price", "type": "double"},
    {"name": "quantity", "type": "double"},
    {"name": "first_trade_id", "type": "long"},
    {"name": "last_trade_id", "type": "long"},
    {"name": "timestamp", "type": "long", "doc": "Trade timestamp (milliseconds)"},
    {"name": "is_buyer_maker", "type": "boolean"},
    {"name": "is_best_match", "type": "boolean"},
    {"name": "collection_ts", "type": "long", "doc": "API collection timestamp"},
    {"name": "api_latency_ms", "type": "int", "doc": "API response latency"},
    {"name": "source", "type": "string", "default": "rest"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

#### REST Depth Snapshot Schema
```json
{
  "type": "record",
  "name": "RESTDepthSnapshot",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "last_update_id", "type": "long"},
    {"name": "bids", "type": {
      "type": "array",
      "items": {
        "type": "record", 
        "fields": [
          {"name": "price", "type": "double"},
          {"name": "quantity", "type": "double"}
        ]
      }
    }},
    {"name": "asks", "type": {
      "type": "array",
      "items": {
        "type": "record",
        "fields": [
          {"name": "price", "type": "double"},
          {"name": "quantity", "type": "double"}
        ]
      }
    }},
    {"name": "snapshot_ts", "type": "long", "doc": "Snapshot timestamp"},
    {"name": "collection_ts", "type": "long"},
    {"name": "api_latency_ms", "type": "int"},
    {"name": "source", "type": "string", "default": "rest"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

#### REST Klines Schema
```json
{
  "type": "record",
  "name": "RESTKline",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "open_time", "type": "long"},
    {"name": "close_time", "type": "long"},
    {"name": "open_price", "type": "double"},
    {"name": "high_price", "type": "double"},
    {"name": "low_price", "type": "double"},
    {"name": "close_price", "type": "double"},
    {"name": "volume", "type": "double"},
    {"name": "quote_volume", "type": "double"},
    {"name": "trade_count", "type": "int"},
    {"name": "taker_buy_volume", "type": "double"},
    {"name": "taker_buy_quote_volume", "type": "double"},
    {"name": "collection_ts", "type": "long"},
    {"name": "source", "type": "string", "default": "rest"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

## Silver Layer (Normalized Data)

### Purpose
- **Data Quality**: Validated, cleaned, and normalized data
- **Unified Schema**: Common format for SBE and REST data
- **Optimized Queries**: Structured for analytical workloads
- **Feature Engineering**: Prepared for ML feature extraction

### 1. One-Minute Bars

#### Directory Structure
```
s3://bitcoin-data-lake/silver/bars_1m/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── bars_1m_20240115_001.parquet
    ├── bars_1m_20240115_002.parquet
    └── bars_1m_20240115_003.parquet
```

#### 1-Minute Bars Schema
```json
{
  "type": "record",
  "name": "OneMinuteBar",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "open_time", "type": "long", "doc": "Bar start time (epoch ms)"},
    {"name": "close_time", "type": "long", "doc": "Bar end time (epoch ms)"},
    
    # OHLCV Data
    {"name": "open_price", "type": "double"},
    {"name": "high_price", "type": "double"},
    {"name": "low_price", "type": "double"},
    {"name": "close_price", "type": "double"},
    {"name": "volume", "type": "double"},
    {"name": "notional", "type": "double", "doc": "Quote asset volume"},
    
    # Trade Statistics
    {"name": "trade_count", "type": "int"},
    {"name": "buy_trade_count", "type": "int"},
    {"name": "sell_trade_count", "type": "int"},
    {"name": "buy_volume", "type": "double"},
    {"name": "sell_volume", "type": "double"},
    {"name": "buy_notional", "type": "double"},
    {"name": "sell_notional", "type": "double"},
    
    # Computed Metrics
    {"name": "vwap", "type": "double", "doc": "Volume-weighted average price"},
    {"name": "volume_imbalance", "type": "double", "doc": "(buy_vol - sell_vol) / total_vol"},
    {"name": "price_range", "type": "double", "doc": "high - low"},
    {"name": "price_change", "type": "double", "doc": "close - open"},
    {"name": "price_change_pct", "type": "double", "doc": "Price change percentage"},
    
    # Data Quality
    {"name": "completeness_score", "type": "double", "doc": "Data completeness 0-1"},
    {"name": "source_mix", "type": "string", "doc": "sbe|rest|mixed"},
    {"name": "gap_seconds", "type": "int", "doc": "Total gap time in seconds"},
    
    # Metadata
    {"name": "created_ts", "type": "long", "doc": "ETL processing timestamp"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

#### Example 1-Minute Bar Record
```python
{
    "symbol": "BTCUSDT",
    "open_time": 1705329600000,  # 2024-01-15 14:00:00
    "close_time": 1705329659999, # 2024-01-15 14:00:59.999
    "open_price": 45230.50,
    "high_price": 45235.75,
    "low_price": 45225.00,
    "close_price": 45232.25,
    "volume": 125.67,
    "notional": 5683245.89,
    "trade_count": 1567,
    "buy_trade_count": 789,
    "sell_trade_count": 778,
    "buy_volume": 65.34,
    "sell_volume": 60.33,
    "buy_notional": 2956123.45,
    "sell_notional": 2727122.44,
    "vwap": 45230.18,
    "volume_imbalance": 0.0399,
    "price_range": 10.75,
    "price_change": 1.75,
    "price_change_pct": 0.0039,
    "completeness_score": 0.98,
    "source_mix": "sbe",
    "gap_seconds": 0,
    "created_ts": 1705329720000,
    "partition_date": "2024-01-15"
}
```

### 2. Order Book Snapshots

#### Directory Structure
```
s3://bitcoin-data-lake/silver/snapshots/BTCUSDT/
└── year=2024/month=01/day=15/hour=14/
    ├── snapshot_20240115_1400.parquet
    ├── snapshot_20240115_1415.parquet
    └── snapshot_20240115_1430.parquet
```

#### Order Book Snapshot Schema
```json
{
  "type": "record",
  "name": "OrderBookSnapshot",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "snapshot_ts", "type": "long", "doc": "Snapshot timestamp (ms)"},
    {"name": "last_update_id", "type": "long"},
    
    # Best Bid/Ask
    {"name": "best_bid_price", "type": "double"},
    {"name": "best_bid_qty", "type": "double"},
    {"name": "best_ask_price", "type": "double"},
    {"name": "best_ask_qty", "type": "double"},
    {"name": "spread", "type": "double"},
    {"name": "spread_bp", "type": "double", "doc": "Spread in basis points"},
    
    # Top 10 Levels
    {"name": "bid_levels", "type": {
      "type": "array",
      "items": {
        "type": "record",
        "fields": [
          {"name": "price", "type": "double"},
          {"name": "quantity", "type": "double"},
          {"name": "value", "type": "double", "doc": "price * quantity"}
        ]
      }
    }},
    {"name": "ask_levels", "type": {
      "type": "array", 
      "items": {
        "type": "record",
        "fields": [
          {"name": "price", "type": "double"},
          {"name": "quantity", "type": "double"},
          {"name": "value", "type": "double"}
        ]
      }
    }},
    
    # Aggregated Metrics
    {"name": "total_bid_value", "type": "double", "doc": "Sum of top 10 bid values"},
    {"name": "total_ask_value", "type": "double", "doc": "Sum of top 10 ask values"},
    {"name": "order_book_imbalance", "type": "double", "doc": "(bid_val - ask_val) / total_val"},
    {"name": "weighted_mid_price", "type": "double", "doc": "Volume-weighted mid price"},
    
    # Data Quality
    {"name": "source", "type": "string"},
    {"name": "levels_count", "type": "int", "doc": "Number of price levels"},
    {"name": "created_ts", "type": "long"},
    {"name": "partition_date", "type": "string"},
    {"name": "partition_hour", "type": "int"}
  ]
}
```

### 3. Aggregated Trade Data

#### Directory Structure
```
s3://bitcoin-data-lake/silver/trades_agg/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── trades_agg_20240115_001.parquet
    └── trades_agg_20240115_002.parquet
```

#### Aggregated Trade Schema
```json
{
  "type": "record",
  "name": "AggregatedTrade",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "trade_id", "type": "long"},
    {"name": "price", "type": "double"},
    {"name": "quantity", "type": "double"},
    {"name": "notional", "type": "double", "doc": "price * quantity"},
    {"name": "timestamp", "type": "long", "doc": "Trade timestamp (ms)"},
    {"name": "is_buyer_maker", "type": "boolean"},
    
    # Enhanced Fields
    {"name": "trade_size_category", "type": "string", "doc": "small|medium|large"},
    {"name": "price_level_distance", "type": "double", "doc": "Distance from mid price"},
    {"name": "sequence_number", "type": "long", "doc": "Monotonic sequence"},
    
    # Data Lineage
    {"name": "source", "type": "string", "doc": "sbe|rest"},
    {"name": "ingest_latency_ms", "type": "int", "doc": "Ingestion delay"},
    {"name": "created_ts", "type": "long"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

## Gold Layer (ML-Ready Data)

### Purpose
- **Feature Engineering**: Optimized feature vectors for ML models
- **Label Generation**: 10-second ahead prediction targets
- **Training Datasets**: Complete datasets for model development
- **Performance**: Columnar format optimized for analytics

### 1. Feature Vectors (2-Second Intervals)

#### Directory Structure
```
s3://bitcoin-data-lake/gold/features_2s/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── features_2s_20240115_001.parquet
    ├── features_2s_20240115_002.parquet
    └── features_2s_20240115_003.parquet
```

#### Feature Vector Schema
```json
{
  "type": "record",
  "name": "FeatureVector",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "feature_ts", "type": "long", "doc": "Feature timestamp (epoch seconds)"},
    {"name": "feature_ts_ms", "type": "long", "doc": "Feature timestamp (epoch ms)"},
    
    # Price Features
    {"name": "price", "type": "double"},
    {"name": "mid_price", "type": "double"},
    {"name": "ret_1s", "type": "double", "doc": "1-second return"},
    {"name": "ret_5s", "type": "double", "doc": "5-second return"},
    {"name": "ret_10s", "type": "double", "doc": "10-second return"},
    {"name": "ret_30s", "type": "double", "doc": "30-second return"},
    {"name": "ret_60s", "type": "double", "doc": "60-second return"},
    
    # Volume Features
    {"name": "volume_1s", "type": "double"},
    {"name": "volume_5s", "type": "double"},
    {"name": "volume_10s", "type": "double"},
    {"name": "volume_30s", "type": "double"},
    {"name": "vol_imbalance_1s", "type": "double"},
    {"name": "vol_imbalance_5s", "type": "double"},
    {"name": "vol_imbalance_10s", "type": "double"},
    
    # Order Book Features
    {"name": "spread_bp", "type": "double"},
    {"name": "ob_imbalance", "type": "double"},
    {"name": "bid_strength", "type": "double"},
    {"name": "ask_strength", "type": "double"},
    {"name": "bid_ask_ratio", "type": "double"},
    {"name": "weighted_mid", "type": "double"},
    
    # Trade Flow Features
    {"name": "trade_intensity_1s", "type": "double"},
    {"name": "trade_intensity_5s", "type": "double"},
    {"name": "avg_trade_size_1s", "type": "double"},
    {"name": "avg_trade_size_5s", "type": "double"},
    {"name": "dollar_volume_1s", "type": "double"},
    {"name": "dollar_volume_5s", "type": "double"},
    
    # Technical Indicators
    {"name": "vwap_dev_1s", "type": "double"},
    {"name": "vwap_dev_5s", "type": "double"},
    {"name": "vwap_dev_10s", "type": "double"},
    {"name": "price_volatility", "type": "double"},
    {"name": "momentum", "type": "double"},
    {"name": "acceleration", "type": "double"},
    
    # Advanced Features
    {"name": "volume_momentum", "type": "double"},
    {"name": "vol_adj_ret_1s", "type": "double"},
    {"name": "vol_adj_ret_5s", "type": "double"},
    {"name": "volume_change_5s", "type": "double"},
    {"name": "dollar_intensity", "type": "double"},
    {"name": "trade_size_trend", "type": "double"},
    {"name": "spread_adj_imbalance", "type": "double"},
    {"name": "mid_last_diff", "type": "double"},
    
    # Temporal Features
    {"name": "hour_sin", "type": "double"},
    {"name": "hour_cos", "type": "double"},
    {"name": "minute_sin", "type": "double"},
    {"name": "minute_cos", "type": "double"},
    {"name": "is_us_hours", "type": "int"},
    {"name": "is_asia_hours", "type": "int"},
    {"name": "is_europe_hours", "type": "int"},
    
    # Interaction Features
    {"name": "price_volume_int", "type": "double"},
    {"name": "spread_momentum_int", "type": "double"},
    {"name": "vol_imbalance_int", "type": "double"},
    {"name": "volatility_intensity_int", "type": "double"},
    
    # Data Quality Features
    {"name": "completeness", "type": "double", "doc": "Feature completeness 0-1"},
    {"name": "data_age_ms", "type": "int", "doc": "Age of underlying data"},
    {"name": "gap_indicator", "type": "boolean", "doc": "True if data gap detected"},
    {"name": "source_quality", "type": "string", "doc": "sbe|rest|mixed|degraded"},
    
    # Metadata
    {"name": "created_ts", "type": "long"},
    {"name": "etl_version", "type": "string"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

### 2. Labels (10-Second Ahead Targets)

#### Directory Structure  
```
s3://bitcoin-data-lake/gold/labels_10s/BTCUSDT/
└── year=2024/month=01/day=15/
    ├── labels_10s_20240115_001.parquet
    ├── labels_10s_20240115_002.parquet
    └── labels_10s_20240115_003.parquet
```

#### Label Schema
```json
{
  "type": "record",
  "name": "PredictionLabel",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "feature_ts", "type": "long", "doc": "Feature timestamp (epoch seconds)"},
    {"name": "target_ts", "type": "long", "doc": "Target timestamp (feature_ts + 10s)"},
    {"name": "feature_ts_ms", "type": "long"},
    {"name": "target_ts_ms", "type": "long"},
    
    # Price Information
    {"name": "current_price", "type": "double", "doc": "Price at feature_ts"},
    {"name": "target_price", "type": "double", "doc": "Price at target_ts"},
    {"name": "price_change", "type": "double", "doc": "target_price - current_price"},
    {"name": "return_10s", "type": "double", "doc": "log(target_price / current_price)"},
    {"name": "return_10s_abs", "type": "double", "doc": "Absolute return"},
    
    # Classification Labels
    {"name": "direction", "type": "int", "doc": "1 if up, -1 if down, 0 if flat"},
    {"name": "direction_binary", "type": "int", "doc": "1 if up, 0 if down"},
    {"name": "magnitude_bucket", "type": "int", "doc": "0-4 magnitude buckets"},
    {"name": "volatility_bucket", "type": "int", "doc": "0-4 volatility buckets"},
    
    # Path Information (what happened during 10s)
    {"name": "max_price_10s", "type": "double", "doc": "Maximum price in 10s window"},
    {"name": "min_price_10s", "type": "double", "doc": "Minimum price in 10s window"},
    {"name": "price_range_10s", "type": "double", "doc": "max - min in 10s window"},
    {"name": "volatility_10s", "type": "double", "doc": "Price volatility in 10s window"},
    {"name": "volume_10s", "type": "double", "doc": "Total volume in 10s window"},
    {"name": "trade_count_10s", "type": "int", "doc": "Number of trades in 10s window"},
    
    # Regression Targets
    {"name": "price_target_scaled", "type": "double", "doc": "Scaled price target"},
    {"name": "return_target_scaled", "type": "double", "doc": "Scaled return target"},
    {"name": "log_return_target", "type": "double", "doc": "Log return target"},
    
    # Multi-horizon Labels (for additional prediction windows)
    {"name": "return_5s", "type": "double", "doc": "5-second ahead return"},
    {"name": "return_15s", "type": "double", "doc": "15-second ahead return"},
    {"name": "return_30s", "type": "double", "doc": "30-second ahead return"},
    
    # Data Quality
    {"name": "is_valid", "type": "boolean", "doc": "True if label is valid"},
    {"name": "gap_in_window", "type": "boolean", "doc": "True if data gap in 10s window"},
    {"name": "data_quality_score", "type": "double", "doc": "Quality score 0-1"},
    {"name": "outlier_flag", "type": "boolean", "doc": "True if outlier"},
    
    # Market Context
    {"name": "market_regime", "type": "string", "doc": "normal|volatile|trending|ranging"},
    {"name": "liquidity_state", "type": "string", "doc": "high|medium|low"},
    {"name": "spread_state", "type": "string", "doc": "tight|normal|wide"},
    
    # Metadata
    {"name": "created_ts", "type": "long"},
    {"name": "etl_version", "type": "string"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

### 3. Training Datasets

#### Directory Structure
```
s3://bitcoin-data-lake/gold/training_sets/BTCUSDT/
├── v1.0/
│   ├── train_2024_01.parquet
│   ├── val_2024_01.parquet
│   └── test_2024_01.parquet
├── v1.1/
│   ├── train_2024_02.parquet
│   ├── val_2024_02.parquet
│   └── test_2024_02.parquet
└── latest/
    ├── train_latest.parquet
    ├── val_latest.parquet
    └── test_latest.parquet
```

#### Training Dataset Schema
```json
{
  "type": "record",
  "name": "TrainingRecord",
  "fields": [
    {"name": "record_id", "type": "string", "doc": "Unique record identifier"},
    {"name": "symbol", "type": "string"},
    {"name": "timestamp", "type": "long"},
    
    # Feature Array (flattened for ML)
    {"name": "features", "type": {
      "type": "array",
      "items": "double"
    }, "doc": "All features as array"},
    
    # Feature Names (for reference)
    {"name": "feature_names", "type": {
      "type": "array", 
      "items": "string"
    }, "doc": "Feature column names"},
    
    # Target Variables
    {"name": "target_price", "type": "double"},
    {"name": "target_return", "type": "double"},
    {"name": "target_direction", "type": "int"},
    
    # Split Information
    {"name": "split", "type": "string", "doc": "train|val|test"},
    {"name": "fold", "type": "int", "doc": "Cross-validation fold"},
    
    # Sample Weights
    {"name": "sample_weight", "type": "double", "doc": "Sample importance weight"},
    {"name": "class_weight", "type": "double", "doc": "Class balancing weight"},
    
    # Metadata
    {"name": "data_version", "type": "string"},
    {"name": "created_ts", "type": "long"},
    {"name": "partition_date", "type": "string"}
  ]
}
```

## ETL Processing Metadata

### 1. Schema Evolution Tracking

#### Schema Version File
```json
// s3://bitcoin-data-lake/config/schemas/schema_versions.json
{
  "bronze": {
    "sbe_trade": {
      "version": "1.2.0",
      "created": "2024-01-15T10:00:00Z",
      "fields_added": ["partition_hour"],
      "fields_removed": [],
      "breaking_changes": false
    },
    "rest_aggtrade": {
      "version": "1.1.0", 
      "created": "2024-01-10T10:00:00Z",
      "fields_added": ["api_latency_ms"],
      "fields_removed": [],
      "breaking_changes": false
    }
  },
  "silver": {
    "one_minute_bar": {
      "version": "2.0.0",
      "created": "2024-01-15T10:00:00Z", 
      "fields_added": ["buy_notional", "sell_notional"],
      "fields_removed": ["old_field"],
      "breaking_changes": true
    }
  },
  "gold": {
    "feature_vector": {
      "version": "1.3.0",
      "created": "2024-01-15T10:00:00Z",
      "fields_added": ["interaction_features"],
      "fields_removed": [],
      "breaking_changes": false
    }
  }
}
```

### 2. ETL Pipeline Configuration

#### ETL Config File
```json
// s3://bitcoin-data-lake/config/pipelines/etl_config.json
{
  "bronze_to_silver": {
    "schedule": "0 5 * * *",
    "batch_size": "1_day",
    "lookback_days": 1,
    "validation_rules": [
      "no_missing_timestamps",
      "price_sanity_check", 
      "volume_sanity_check",
      "sequence_continuity"
    ],
    "output_compression": "snappy",
    "partitioning": ["year", "month", "day"]
  },
  "silver_to_gold": {
    "schedule": "0 7 * * *",
    "batch_size": "1_day",
    "feature_windows": [1, 5, 10, 30, 60],
    "label_horizons": [5, 10, 15, 30],
    "quality_threshold": 0.8,
    "outlier_detection": true,
    "feature_scaling": "robust",
    "output_format": "parquet"
  }
}
```

## Data Retention and Lifecycle

### 1. S3 Lifecycle Policies

```yaml
# Bronze Layer Retention
bronze_lifecycle:
  - transition_days: 30
    storage_class: IA  # Infrequent Access
  - transition_days: 90  
    storage_class: GLACIER
  - transition_days: 2555  # 7 years
    storage_class: DEEP_ARCHIVE

# Silver Layer Retention  
silver_lifecycle:
  - transition_days: 90
    storage_class: IA
  - transition_days: 365
    storage_class: GLACIER
  - transition_days: 1825  # 5 years
    storage_class: DEEP_ARCHIVE

# Gold Layer Retention
gold_lifecycle:
  - transition_days: 180
    storage_class: IA
  - transition_days: 730
    storage_class: GLACIER
  - transition_days: 1095  # 3 years
    storage_class: DEEP_ARCHIVE
```

### 2. Data Access Patterns

```python
# Optimized S3 access patterns
ACCESS_PATTERNS = {
    "realtime_training": {
        "layer": "gold",
        "time_range": "last_30_days",
        "storage_class": "standard",
        "query_frequency": "daily"
    },
    "model_validation": {
        "layer": "gold", 
        "time_range": "last_90_days",
        "storage_class": "standard",
        "query_frequency": "weekly"
    },
    "historical_analysis": {
        "layer": "silver",
        "time_range": "last_2_years", 
        "storage_class": "IA",
        "query_frequency": "monthly"
    },
    "audit_compliance": {
        "layer": "bronze",
        "time_range": "all_data",
        "storage_class": "glacier",
        "query_frequency": "rarely"
    }
}
```

This S3 schema provides comprehensive data lake capabilities for the Bitcoin prediction pipeline, enabling efficient storage, processing, and analysis of market data across bronze, silver, and gold layers while optimizing for both operational performance and cost efficiency.