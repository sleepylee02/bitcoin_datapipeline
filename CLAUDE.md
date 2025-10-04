# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a real-time Bitcoin trading data pipeline that ingests market data from Binance, processes it through stream processing, and runs ML inference for trading signals. The system is designed for low-latency (<100ms p95) real-time predictions with robust fallback mechanisms for handling stale or missing data.

## Architecture

The pipeline follows this flow:

1. **Ingestor Service**: Consumes Binance WebSocket (real-time) and REST API (historical/backfill)
   - Normalizes data to Avro/Proto schemas
   - Emits to Kinesis Data Streams (KDS)
   - Provides heartbeat monitoring

2. **Stream Processing (Flink/Kinesis Data Analytics)**:
   - Computes rolling features: VWAP, volatility, order book imbalance, price momentum
   - Writes features to Redis with TTL for real-time serving
   - Splits to S3/Iceberg for data lake storage via Kinesis Firehose

3. **Inference Service (ECS/EKS)**:
   - Consumes from KDS
   - Fetches features from Redis with fallback controller:
     1. Fresh online features (within latency budget)
     2. Repair stale data with delta corrections
     3. Impute via EMA/Kalman carry-forward
     4. Pull microbatch features from S3/Iceberg
     5. Safe mode (no-trade) if all fail
   - Runs model inference (ONNX/TensorRT/XGBoost)
   - Inline risk engine with circuit breakers

4. **Feature Store (Feast)**:
   - Offline: Iceberg tables on S3
   - Online: Redis/DynamoDB
   - Provides point-in-time correct features for training and serving

5. **Training Pipeline**:
   - Incremental training: every 5 minutes (update head/small learner)
   - Full retrain: every 6-24 hours (rebuild base model)
   - Model registry: SageMaker/MLflow with shadow → canary → full deployment

6. **Orchestration**:
   - Airflow (MWAA): batch ETL, retrain, quality checks
   - EventBridge: triggers for incremental updates
   - Step Functions: model deployment workflows
   - CloudWatch/Prometheus: metrics and monitoring

## Data Schemas

### Market Data (Avro)
```json
{
  "symbol": "string",
  "timestamp": "long",
  "price": "double",
  "volume": "double",
  "bid_price": "double",
  "ask_price": "double",
  "source": "string"
}
```

### Model Input
```python
@dataclass
class ModelInput:
    symbol: str
    timestamp: int
    price: float
    vwap: float
    volatility: float
    imbalance: float
    momentum: Dict[str, float]
```

### Prediction Output
```python
@dataclass
class Prediction:
    symbol: str
    timestamp: int
    signal: float  # -1 to 1
    confidence: float  # 0 to 1
    risk_score: float
    should_trade: bool
```

## Redis Feature Schema
```
Key: "features:{symbol}:{window}"
Value: JSON with TTL of 300s
{
  "vwap": 45230.50,
  "volatility": 0.023,
  "imbalance": 0.15,
  "timestamp": 1638360000,
  "ttl": 300
}
```

## Configuration

Environment-specific configs are in `config/`:
- `local.yaml`: Local development with Docker Compose
- `dev.yaml`: Development environment
- `prod.yaml`: Production settings

Secrets management:
- Local: `.env` files
- Production: AWS Secrets Manager

## Critical Latency Requirements

- **p95 inference latency**: <100ms
- **Feature freshness**: <60s (triggers staleness alerts)
- **Heartbeat interval**: 30s

## Development Setup

### Local Infrastructure (Docker Compose)
The local environment includes:
- Kinesis (LocalStack)
- Redis
- Flink JobManager/TaskManager
- S3 (LocalStack)

### Testing Strategy

**Unit Tests**:
- Schema validation and serialization
- Feature computation logic
- Model inference
- Fallback controller logic

**Integration Tests**:
- End-to-end data flow
- Binance API mocking
- Redis feature serving
- Model registry integration
- Local Kinesis with LocalStack

**Performance Tests**:
- Latency benchmarks (ensure p95 <100ms)
- Throughput testing
- Memory/CPU profiling
- Backpressure handling

## Monitoring & Alerts

### Business Metrics
- Prediction accuracy
- Trade P&L
- Feature freshness
- Model drift

### Technical Metrics
- Latency (p50, p95, p99)
- Throughput
- Error rates
- Resource utilization

### Alert Rules
- Feature staleness >60s → Slack alert
- Inference latency p95 >100ms → PagerDuty
- WebSocket disconnection → Trigger fallback mechanism

## Key Implementation Notes

### WebSocket Disconnection Handling
When WebSocket disconnects, use the FallbackController to maintain service:
1. Use last-known-good values from Redis
2. Apply delta corrections for slight staleness
3. Use EMA/Kalman filtering for imputation
4. Pull microbatch from S3/Iceberg as last resort
5. Enter safe mode (no-trade) if all fail

### Incremental vs Full Training
- **Incremental**: Update model head every 5 minutes with recent data
- **Full retrain**: Rebuild entire model every 6-24 hours
- Always validate on point-in-time correct features from Feast

### Model Deployment
Follow safe deployment pattern:
1. Shadow mode (log predictions, no action)
2. Canary deployment (1-5% traffic)
3. Full rollout (monitor for drift/degradation)
