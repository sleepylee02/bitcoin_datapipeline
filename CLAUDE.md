# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a **real-time Bitcoin price prediction service** that predicts Bitcoin price **10 seconds ahead** with predictions generated **every 2 seconds**. The system uses a hot-path architecture with atomic re-anchoring for zero-downtime reliability, achieving sub-100ms inference latency.

## Architecture

The system implements a **tri-layer architecture** with atomic re-anchoring for reliability:

### 1. Hot Path (Real-time Inference) 
**SBE WebSocket → Kinesis → Lambda/KDA → Redis → Inference (every 2s)**
- SBE client streams trades, order book, and best bid/ask data
- Kinesis Data Streams with Lambda/KDA processors for low latency
- Redis stores hot state: order books, rolling trade stats, feature vectors
- Inference service reads Redis only, predicts 10 seconds ahead every 2 seconds
- **Critical**: Hot path never waits for REST API or S3 operations

### 2. Reliability Path (Gap Prevention & Recovery)
**REST API (1-min) → Gap Detection → Atomic Re-anchor → S3 Backfill**
- REST client polls every 1 minute for depth snapshots and aggregate trades
- Sequence monitoring detects gaps in SBE stream
- Atomic Redis key swapping during re-anchoring (no downtime)
- S3 bronze layer receives all raw data for historical analysis
- **Critical**: Recovery operations never block the hot inference path

### 3. Training Pipeline (Model Development)
**S3 Bronze → Silver → Gold → Model Training → Deployment**
- S3 bronze: Raw SBE events and REST responses
- S3 silver: Normalized snapshots and 1-minute bars  
- S3 gold: Feature vectors (2s intervals) and labels (10s ahead targets)
- Lightweight MLP training optimized for <100ms inference
- Model deployment to inference service without hot path interruption

## Data Schemas

### Redis Hot State Schema
```
# Order Book (no TTL - always live)
ob:BTCUSDT (HASH): {
  "best_bid": 45229.50, "best_ask": 45231.00, "spread": 1.50,
  "bid1_p": 45229.50, "bid1_q": 1.5, ..., "ask10_p": 45240.00, "ask10_q": 0.8,
  "ts_us": 1638360000123456
}

# Rolling Trade Stats (5min TTL)
tr:BTCUSDT:1s (HASH): {"count": 15, "vol": 12.5, "signed_vol": 2.3, "vwap_minus_mid": 0.05, "last_ts_us": 1638360000}
tr:BTCUSDT:5s (HASH): {"count": 75, "vol": 65.2, "signed_vol": 8.7, "vwap_minus_mid": 0.12, "last_ts_us": 1638360000}

# Feature Vector (2min TTL)
feat:BTCUSDT (HASH): {"ret_1s": 0.0002, "ret_5s": 0.0015, "vol_imbalance": 0.03, "spread_bp": 3.3, "ts": 1638360000}

# Re-anchor Flag
reanchor:BTCUSDT (FLAG): Set during atomic recovery operations
```

### Prediction Output Schema
```python
@dataclass
class Prediction:
    symbol: str = "BTCUSDT"
    timestamp: int              # Current time (ms)
    current_price: float
    predicted_price_10s: float  # Price 10 seconds ahead
    confidence: float           # 0.0 - 1.0
    latency_ms: int            # Inference latency
    model_version: str
    features_age_ms: int       # Age of input features
    source: str                # "redis" or "fallback"
```

### S3 Data Lake Schema
```
# Bronze Layer (Raw Events)
s3://bitcoin-data-lake/bronze/sbe/{symbol}/year={}/month={}/day={}/hour={}/*.parquet
s3://bitcoin-data-lake/bronze/rest/{symbol}/{data_type}/year={}/month={}/day={}/*.parquet

# Silver Layer (Normalized)  
s3://bitcoin-data-lake/silver/snapshots/{symbol}/year={}/month={}/day={}/*.parquet
s3://bitcoin-data-lake/silver/bars_1m/{symbol}/year={}/month={}/day={}/*.parquet

# Gold Layer (ML Ready)
s3://bitcoin-data-lake/gold/features_2s/{symbol}/year={}/month={}/day={}/*.parquet
s3://bitcoin-data-lake/gold/labels_10s/{symbol}/year={}/month={}/day={}/*.parquet
```

## Service Architecture

```
services/
├── ingestor/          # Dual-mode: SBE streaming + REST gap detection
│   ├── sbe-mode/      # Real-time SBE → Kinesis (hot path)
│   └── rest-mode/     # 1-min polling → gap detection → atomic re-anchor
├── aggregator/        # Kinesis → Redis state management + atomic operations
│   ├── redis-writer/  # Order book maintenance, rolling trade stats
│   └── reanchor/      # Atomic key swapping during recovery
├── inference/         # Redis-only reads → 10s prediction (every 2s)
│   ├── feature-reader/# Redis hot state consumption
│   └── predictor/     # Lightweight MLP inference <100ms
├── trainer/           # S3 gold → model training → deployment
│   ├── feature-eng/   # S3 bronze → silver → gold pipeline
│   └── model-dev/     # MLP training optimized for inference speed
└── lambda-functions/  # Event-driven processing
    ├── gap-detector/  # SBE sequence monitoring
    ├── rest-puller/   # 1-min REST polling and re-anchor trigger
    └── s3-processor/  # Bronze → silver ETL
```

## Configuration

Environment-specific configs are in each service's `config/` directory:
- `local.yaml`: LocalStack + Redis for development
- `dev.yaml`: AWS services with reduced scale
- `prod.yaml`: Production scale with high availability

## Critical Requirements

- **Prediction target**: Bitcoin price 10 seconds ahead
- **Prediction frequency**: Every 2 seconds
- **Inference latency**: <100ms per prediction (P99)
- **Hot path isolation**: Inference never waits for REST/S3 operations
- **Zero downtime**: Atomic re-anchoring during gap recovery
- **Feature freshness**: <2s for optimal predictions
- **Service availability**: 99.9% uptime with graceful degradation

## Development Setup

### Local Infrastructure (Docker Compose)
```yaml
# docker-compose.yml includes:
- LocalStack (S3, Kinesis Data Streams)
- Redis Cluster (hot state storage)
- Mock SBE stream generator
- Prometheus/Grafana (monitoring)
```

### Running Locally
```bash
# Start infrastructure
docker-compose up -d

# Test hot path
cd test/ && python unit/test_redis_hotpath.py

# Run services (in separate terminals)
cd services/ingestor && python src/sbe_mode.py      # SBE → Kinesis → Redis
cd services/aggregator && python src/redis_writer.py # Maintain Redis state
cd services/inference && python src/predictor.py    # Redis → predictions

# Test atomic re-anchor
cd services/ingestor && python src/rest_mode.py     # Trigger re-anchor
```

## Deployment

### AWS Architecture
- **ECS/Fargate**: Containerized services with auto-scaling
- **Kinesis Data Streams**: SBE event streaming with Lambda processors
- **ElastiCache Redis**: Hot state storage with cluster mode
- **S3 Data Lake**: Bronze/silver/gold layers for training
- **RDS Aurora**: Curated data for dashboards and audit logs
- **Lambda Functions**: Event-driven gap detection and recovery

### Deployment Strategy
- **Hot Path**: ECS services with dedicated resources, no auto-scaling disruption
- **Reliability Path**: Lambda functions triggered by EventBridge (1-min schedule)
- **Training Pipeline**: Step Functions orchestrating S3 ETL and model training
- **Monitoring**: CloudWatch dashboards with sub-100ms latency alerts

## Monitoring

### Hot Path Metrics (Critical)
- **Inference Latency**: P50/P95/P99 <100ms for all predictions
- **Prediction Frequency**: Exactly every 2 seconds (no missed cycles)
- **Feature Freshness**: Redis feature age <2s (triggers degraded mode at >5s)
- **Redis Hit Rate**: >99% for hot state reads
- **SBE Stream Health**: Message rate, decode errors, sequence gaps

### Reliability Metrics
- **Gap Detection**: False positive/negative rates for sequence monitoring  
- **Re-anchor Duration**: Time for atomic Redis key swapping
- **Recovery Success Rate**: Successful gap recovery without inference disruption
- **REST API Health**: Latency and error rates for 1-min polling

### Business Metrics
- **Prediction Accuracy**: 10-second ahead price prediction error rates
- **Model Performance**: Directional accuracy, confidence calibration
- **Service Availability**: 99.9% uptime excluding planned maintenance

### Health Checks
- `/health` endpoint: Redis connectivity, feature freshness, model status
- `/ready` endpoint: Service ready for traffic (post-warmup)
- `/metrics` endpoint: Prometheus-format metrics for monitoring
- Redis cluster health: Memory usage, connection pool status

## Development Guidelines

- **Hot path first**: Never compromise inference latency for additional features
- **Atomic operations**: Use Redis atomic commands for state updates during re-anchoring
- **Graceful degradation**: Design fallbacks that maintain service availability
- **Event-driven**: Use AWS native event services (Kinesis, EventBridge, Lambda)
- **Monitoring driven**: Every operation must be measurable and alertable
- **Zero-downtime**: All updates must support rolling deployments

## Important Reminders

- **Hot path isolation**: Inference service reads Redis only, never REST/S3
- **Atomic re-anchoring**: Recovery operations use key swapping, never clearing Redis
- **Sub-100ms requirement**: P99 inference latency is a hard constraint
- **2-second frequency**: Predictions must be generated exactly every 2 seconds
- **10-second target**: All predictions are for price 10 seconds ahead
- **Test atomicity**: Validate atomic operations in local Redis before deployment
