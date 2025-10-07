# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a real-time Bitcoin price prediction service that ingests market data from Binance and provides price predictions every 1-2 seconds using a simple MLP model. The system is designed for low-latency (<100ms) real-time inference with a focus on simplicity and reliability.

## Architecture

The system follows two main data flows:

### 1. Historical Data Pipeline (Training)
**REST API → S3 → RDBMS → Model Training**
- REST client fetches historical data from Binance
- Raw data stored in S3 bronze layer  
- Data connector transforms and loads into PostgreSQL
- Training pipeline uses RDBMS data to train MLP model

### 2. Real-time Inference Pipeline  
**SBE WebSocket → Kinesis → Aggregation → Redis → Inference**
- SBE client streams real-time market data
- Kinesis Data Streams for reliable message delivery
- Aggregation service computes features every N records
- Redis stores latest features with TTL
- Inference service predicts price every 1-2 seconds

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

### Prediction Output
```python
@dataclass
class Prediction:
    symbol: str
    timestamp: int
    predicted_price: float
    confidence: float
    latency_ms: int
```

## Redis Feature Schema
```
Key: "features:{symbol}:{timestamp}"
Value: JSON with TTL of 60s
{
  "price": 45230.50,
  "volume": 123.45,
  "vwap": 45225.30,
  "price_change": 0.02,
  "timestamp": 1638360000
}
```

## Service Architecture

```
services/
├── ingestor/          # REST + SBE data ingestion
├── aggregator/        # Kinesis → Redis feature aggregation  
├── inference/         # MLP price prediction service
├── trainer/           # Model training pipeline
└── data-connector/    # S3 → PostgreSQL ETL
```

## Configuration

Environment-specific configs are in each service's `config/` directory:
- `local.yaml`: Local development with Docker Compose
- `dev.yaml`: Development environment
- `prod.yaml`: Production settings

## Critical Requirements

- **Inference latency**: <100ms per prediction
- **Prediction frequency**: Every 1-2 seconds
- **Feature freshness**: <5s (triggers fallback)
- **Service availability**: 99.9% uptime

## Development Setup

### Local Infrastructure (Docker Compose)
```yaml
# docker-compose.yml includes:
- LocalStack (S3, Kinesis)
- Redis
- PostgreSQL
- Prometheus/Grafana
```

### Running Locally
```bash
# Start infrastructure
docker-compose up -d

# Run services
cd services/ingestor && python src/main.py
cd services/aggregator && python src/main.py  
cd services/inference && python src/main.py
```

## Deployment

### Dockerization
Each service includes:
- `Dockerfile` for containerization
- Health check endpoints
- Graceful shutdown handling
- Resource limits

### AWS Deployment
- **EC2 instances** for service hosting
- **Kinesis Data Streams** for messaging
- **ElastiCache Redis** for feature store
- **RDS PostgreSQL** for training data
- **S3** for raw data storage

## Monitoring

### Key Metrics
- **Latency**: End-to-end prediction time
- **Throughput**: Predictions per second
- **Accuracy**: Model prediction quality
- **Availability**: Service uptime

### Health Checks
- `/health` endpoint for each service
- Redis connectivity
- Database connectivity
- Model loading status

## Development Guidelines

- **Simplicity first**: Focus on core functionality over complex features
- **Real-time focused**: Optimize for low-latency prediction pipeline
- **Modular services**: Each service has single responsibility
- **AWS native**: Use managed AWS services where possible
- **Monitoring**: Include health checks and metrics in all services

## Important Reminders

- Focus on the real-time prediction pipeline
- Keep services lightweight and focused  
- Prefer existing AWS services over custom solutions
- Test locally with Docker Compose before AWS deployment
