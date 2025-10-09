# Bitcoin Pipeline Architecture

## Overview

This is a **real-time Bitcoin price prediction system** that predicts price movements **10 seconds ahead** with new predictions generated **every 2 seconds**. The architecture prioritizes **sub-100ms inference latency** through a hot path design with **atomic re-anchoring** for zero-downtime reliability.

## Architecture Principles

### 1. Hot Path Isolation
The inference pipeline reads **Redis only** and never waits for REST APIs or S3 operations. This ensures consistent sub-100ms latency.

### 2. Atomic Re-anchoring
Gap recovery uses **atomic Redis key swapping** instead of clearing state, maintaining service availability during recovery operations.

### 3. Tri-layer Data Storage
- **Redis**: Hot state for real-time inference
- **S3**: Data lake for training and historical analysis  
- **RDS**: Curated data for dashboards and audit logs

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                          HOT PATH (Real-time)                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  SBE WebSocket ──► Kinesis ──► Lambda/KDA ──► Redis ──► Inference│
│  (trades/depth/  │ Data     │ Processors  │ Hot    │ Service    │
│   bestBidAsk)    │ Streams  │            │ State  │ (every 2s) │
│                  │          │            │        │            │
│                  │          │            │        ▼            │
│                  │          │            │   ┌─────────────┐   │
│                  │          │            │   │ 10s Price   │   │
│                  │          │            │   │ Predictions │   │
│                  │          │            │   └─────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────┐
│                     RELIABILITY PATH (Gap Recovery)             │
├─────────────────────────────────────────────────────────────────┤
│                                   │                             │
│  REST API ──► Gap Detection ──► Atomic Re-anchor ──► S3 Backfill│
│  (1-min poll) │ (sequence     │ (key swapping)    │            │
│               │  monitoring)  │                   │            │
│               │               │                   │            │
│               ▼               ▼                   ▼            │
│         ┌──────────┐    ┌──────────┐       ┌──────────┐       │
│         │EventBridge│    │Redis Temp│       │S3 Bronze │       │
│         │(triggers) │    │Keys      │       │Layer     │       │
│         └──────────┘    └──────────┘       └──────────┘       │
└─────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────┐
│                    TRAINING PATH (Model Development)            │
├─────────────────────────────────────────────────────────────────┤
│                                   │                             │
│  S3 Bronze ──► S3 Silver ──► S3 Gold ──► Model Training ──► Deploy│
│  (raw data)  │ (normalized) │ (features/ │ (lightweight   │ to   │
│              │              │  labels)   │  MLP)          │ ECS  │
│              │              │            │                │      │
│              ▼              ▼            ▼                ▼      │
│        ┌──────────┐   ┌──────────┐ ┌──────────┐    ┌──────────┐ │
│        │ETL       │   │Feature   │ │Training  │    │Model     │ │
│        │Pipeline  │   │Engineering│ │Pipeline  │    │Registry  │ │
│        └──────────┘   └──────────┘ └──────────┘    └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Data Flow Details

### Hot Path (SBE → Inference)

#### 1. SBE Data Ingestion
```
SBE WebSocket Events:
├── Trade Events        → market-sbe-trade stream
├── Depth Updates       → market-sbe-depth stream  
└── Best Bid/Ask        → market-sbe-bestbidask stream
```

#### 2. Real-time Processing
```
Kinesis Data Streams → Lambda/KDA Functions → Redis Updates
                                           ├── Order Book Maintenance
                                           ├── Rolling Trade Statistics  
                                           └── Feature Vector Updates
```

#### 3. Inference Pipeline
```
Every 2 seconds:
Redis Read → Feature Extraction → MLP Model → 10s Price Prediction
  (<5ms)         (<10ms)           (<30ms)         (<50ms total)
```

### Reliability Path (Gap Recovery)

#### 1. Gap Detection
```
EventBridge (1-min) → Lambda Gap Detector
                   ├── Sequence ID monitoring
                   ├── Timestamp validation
                   └── Volume consistency checks
```

#### 2. Atomic Re-anchoring Process
```
Gap Detected → REST API Calls → Temporary Redis Keys → Atomic Swap
             ├── /depth snapshot       ├── ob:new:BTCUSDT      ├── RENAME commands
             ├── /aggTrades backfill   ├── tr:new:BTCUSDT:1s   └── Cleanup temp keys
             └── /klines validation    └── feat:new:BTCUSDT
```

#### 3. S3 Backfill
```
REST Data → S3 Bronze Layer → EventBridge → ETL Pipeline
```

### Training Path (Model Development)

#### 1. Data Lake Pipeline
```
S3 Bronze (Raw) → S3 Silver (Normalized) → S3 Gold (ML Ready)
├── Parquet format     ├── 1-minute bars        ├── Feature vectors (2s)
├── Partitioned by     ├── Order book snapshots ├── Labels (10s ahead)  
│   hour/day/month     └── Trade aggregations   └── Training datasets
```

#### 2. Model Training
```
S3 Gold → Feature Engineering → MLP Training → Model Export
       ├── 2-second alignment    ├── Lightweight arch  ├── ONNX format
       ├── 10-second labels      ├── <100ms inference  └── Model registry
       └── Time-series split     └── Hyperparameter opt
```

## Redis Hot State Schema

### Key Naming Convention
```
ob:{symbol}           # Order book (no TTL)
tr:{symbol}:{window}  # Trade statistics (5min TTL)
feat:{symbol}         # Feature vector (2min TTL)
reanchor:{symbol}     # Re-anchor flag (temp)
```

### Order Book State
```redis
ob:BTCUSDT (HASH):
├── best_bid: "45229.50"
├── best_ask: "45231.00"  
├── spread: "1.50"
├── bid1_p: "45229.50", bid1_q: "1.5"
├── bid2_p: "45229.00", bid2_q: "2.1"
├── ...
├── ask10_p: "45240.00", ask10_q: "0.8"
└── ts_us: "1638360000123456"
```

### Rolling Trade Statistics
```redis
tr:BTCUSDT:1s (HASH):      # 1-second window (5min TTL)
├── count: "15"             # Number of trades
├── vol: "12.5"            # Volume
├── signed_vol: "2.3"      # Buy volume - sell volume
├── vwap_minus_mid: "0.05" # VWAP deviation from mid
├── interarr_mean: "0.067" # Mean time between trades
├── interarr_var: "0.023"  # Variance of inter-arrival times
└── last_ts_us: "1638360000123456"

tr:BTCUSDT:5s (HASH):      # 5-second window (5min TTL)
├── count: "75"
├── vol: "65.2"
├── signed_vol: "8.7"
├── vwap_minus_mid: "0.12"
└── last_ts_us: "1638360000123456"
```

### Feature Vector
```redis
feat:BTCUSDT (HASH):       # 2-minute TTL
├── ret_1s: "0.0002"       # 1-second return
├── ret_5s: "0.0015"       # 5-second return
├── vol_imbalance: "0.03"  # Volume imbalance
├── spread_bp: "3.3"       # Spread in basis points
├── ob_imbalance: "0.15"   # Order book imbalance
├── trade_intensity: "1.2" # Trades per second
└── ts: "1638360000"       # Feature timestamp
```

## Atomic Re-anchoring Procedure

### 1. Pre-conditions
- Gap detected in SBE stream (sequence ID jump or time gap)
- `reanchor:BTCUSDT` flag set to prevent concurrent operations
- REST API connectivity validated

### 2. Data Collection
```python
# Parallel REST API calls
depth_snapshot = await binance.get_depth("BTCUSDT", limit=100)
recent_trades = await binance.get_agg_trades("BTCUSDT", from_time=gap_start)
klines_check = await binance.get_klines("BTCUSDT", "1m", limit=5)
```

### 3. Temporary Key Building
```python
# Build new state in temporary keys
await redis.hset("ob:new:BTCUSDT", depth_snapshot)
await redis.hset("tr:new:BTCUSDT:1s", trade_stats_1s)
await redis.hset("tr:new:BTCUSDT:5s", trade_stats_5s)
await redis.hset("feat:new:BTCUSDT", feature_vector)
```

### 4. Atomic Swap
```python
# Atomic rename operations (all succeed or all fail)
pipeline = redis.pipeline()
pipeline.rename("ob:new:BTCUSDT", "ob:BTCUSDT")
pipeline.rename("tr:new:BTCUSDT:1s", "tr:BTCUSDT:1s")
pipeline.rename("tr:new:BTCUSDT:5s", "tr:BTCUSDT:5s")
pipeline.rename("feat:new:BTCUSDT", "feat:BTCUSDT")
pipeline.delete("reanchor:BTCUSDT")
pipeline.execute()  # All operations are atomic
```

### 5. Post-anchor Validation
- Verify key existence and data integrity
- Resume SBE stream processing
- Log re-anchor metrics and duration

## Performance Specifications

### Latency Requirements
```
Component              Target    P99 Max
─────────────────────────────────────────
Redis Read            < 1ms     < 3ms
Feature Extraction    < 5ms     < 10ms  
MLP Inference         < 20ms    < 40ms
Output Serialization  < 5ms     < 10ms
─────────────────────────────────────────
Total Inference       < 30ms    < 100ms
```

### Throughput Requirements
```
Metric                 Target        Peak
─────────────────────────────────────────
Predictions/sec        0.5 (every 2s) 1.0
SBE Events/sec         1,000         5,000
Redis Ops/sec          10,000        50,000
Kinesis Records/sec    5,000         25,000
```

### Availability Requirements
```
Service               Uptime    Recovery Time
──────────────────────────────────────────
Inference Service     99.9%     < 30s
Redis Cluster         99.95%    < 10s (failover)
Kinesis Streams       99.99%    N/A (managed)
Re-anchor Process     N/A       < 60s
```

## Failure Scenarios and Recovery

### 1. SBE Stream Disconnection
```
Detection: No events for >5 seconds
Response: 
├── Continue inference from Redis (stale data grace period)
├── Attempt SBE reconnection
└── If failed: Trigger REST re-anchor
```

### 2. Redis Cluster Failure
```
Detection: Connection timeout or cluster split
Response:
├── Failover to Redis replica (automatic)
├── If total failure: Degrade to direct REST API mode
└── Alert ops team for manual intervention
```

### 3. Gap Detection False Positives
```
Prevention:
├── Multiple validation criteria (sequence + time + volume)
├── Configurable thresholds per environment
└── Manual override capability
```

### 4. Model Loading Failure
```
Detection: Model inference timeout or error
Response:
├── Reload model from S3/model registry
├── If failed: Use last-known-good model
└── If none available: Return confidence=0 predictions
```

## Monitoring and Alerting

### Critical Alerts (PagerDuty)
- Inference latency P99 > 100ms for >2 minutes
- Prediction frequency deviation >10% for >5 minutes  
- Redis cluster failure or split-brain
- SBE stream disconnected >60 seconds

### Warning Alerts (Slack)
- Feature freshness >5 seconds
- Gap detection triggered
- Re-anchor operation duration >60 seconds
- Model accuracy degradation >20%

### Dashboard Metrics
- Real-time inference latency histogram
- Prediction accuracy rolling 1-hour window
- Redis hit rate and memory usage
- SBE stream health and gap frequency
- Re-anchor success rate and duration

## Security Considerations

### Network Security
- VPC with private subnets for Redis and inference
- Security groups restricting access to necessary ports
- NAT Gateway for outbound Binance API calls

### Data Security  
- Encryption in transit (TLS) for all communications
- Encryption at rest for S3 and RDS
- No sensitive data in Redis (market data only)
- API keys stored in AWS Secrets Manager

### Access Control
- IAM roles with minimal permissions
- Service-to-service authentication via IAM roles
- No hardcoded credentials in code or configuration
- CloudTrail logging for all AWS API calls

This architecture provides a robust foundation for real-time Bitcoin price prediction with sub-100ms latency and zero-downtime reliability through atomic re-anchoring.