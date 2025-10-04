# Bitcoin Data Pipeline - Detailed Implementation Plan

## Project Structure
```
Bitcoin_datapipeline/
├── services/
│   ├── ingestor/
│   │   ├── src/
│   │   ├── config/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── flink-processor/
│   │   ├── src/
│   │   ├── config/
│   │   └── Dockerfile
│   ├── inference/
│   │   ├── src/
│   │   ├── models/
│   │   ├── config/
│   │   └── Dockerfile
│   └── feature-store/
├── schemas/
│   ├── avro/
│   └── proto/
├── infrastructure/
│   ├── terraform/
│   ├── docker-compose.yml
│   └── k8s/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/
```

## Phase 1: Core Data Ingestion (Week 1-2)

### 1.1 Data Schemas
- **Market Data Schema (Avro)**
  ```json
  {
    "type": "record",
    "name": "MarketData",
    "fields": [
      {"name": "symbol", "type": "string"},
      {"name": "timestamp", "type": "long"},
      {"name": "price", "type": "double"},
      {"name": "volume", "type": "double"},
      {"name": "bid_price", "type": "double"},
      {"name": "ask_price", "type": "double"},
      {"name": "source", "type": "string"}
    ]
  }
  ```

- **Trade Schema (Avro)**
- **Orderbook Schema (Avro)**

### 1.2 Ingestor Service
- **Technology**: Python with asyncio
- **Components**:
  - Binance WebSocket client
  - Binance REST API client
  - Avro serializer
  - Kinesis producer
  - Health check endpoint
  - Metrics collection

- **Configuration**:
  ```yaml
  binance:
    websocket_url: "wss://stream.binance.com:9443/ws/"
    rest_api_url: "https://api.binance.com"
    symbols: ["BTCUSDT", "ETHUSDT"]

  kinesis:
    stream_name: "bitcoin-market-data"
    region: "us-east-1"

  heartbeat:
    interval_seconds: 30
  ```

### 1.3 Testing Strategy
- **Unit Tests**: Schema validation, serialization
- **Integration Tests**: Binance API mocking
- **E2E Tests**: Local Kinesis with LocalStack

## Phase 2: Stream Processing (Week 3-4)

### 2.1 Flink Processor
- **Features to Compute**:
  - VWAP (Volume Weighted Average Price)
  - Rolling volatility (1min, 5min, 15min windows)
  - Order book imbalance
  - Price momentum indicators

- **Redis Schema**:
  ```
  Key: "features:{symbol}:{window}"
  Value: JSON with TTL
  {
    "vwap": 45230.50,
    "volatility": 0.023,
    "imbalance": 0.15,
    "timestamp": 1638360000,
    "ttl": 300
  }
  ```

### 2.2 Infrastructure Setup
- **Local Development**: Docker Compose with:
  - Kinesis (LocalStack)
  - Redis
  - Flink JobManager/TaskManager
  - S3 (LocalStack)

## Phase 3: Inference Engine (Week 5-6)

### 3.1 Model Interface
- **Input Schema**:
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

- **Output Schema**:
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

### 3.2 Fallback Controller Logic
```python
class FallbackController:
    def get_features(self, symbol: str) -> ModelInput:
        # 1. Try Redis (fresh features)
        # 2. Apply delta corrections for stale data
        # 3. Use EMA/Kalman filtering
        # 4. Fallback to S3 microbatch
        # 5. Safe mode if all fail
```

## Phase 4: Feature Store & Training (Week 7-8)

### 4.1 Feast Configuration
```yaml
project: bitcoin-trading
registry: s3://bitcoin-features/registry.db
provider: aws
online_store:
  type: redis
  connection_string: "redis://localhost:6379"
offline_store:
  type: file
  path: s3://bitcoin-features/offline
```

### 4.2 Training Pipeline
- **Incremental Training**: Every 5 minutes
- **Full Retrain**: Every 6 hours
- **Model Artifacts**: ONNX format for inference

## Phase 5: Monitoring & Orchestration (Week 9-10)

### 5.1 Metrics to Track
- **Business Metrics**:
  - Prediction accuracy
  - Trade P&L
  - Feature freshness
  - Model drift

- **Technical Metrics**:
  - Latency (p50, p95, p99)
  - Throughput
  - Error rates
  - Resource utilization

### 5.2 Alerting Rules
```yaml
alerts:
  - name: "Feature Staleness"
    condition: "feature_age > 60s"
    action: "slack_alert"

  - name: "Model Latency"
    condition: "inference_latency_p95 > 100ms"
    action: "pagerduty"
```

## Testing Strategy

### Unit Tests
- Schema validation
- Feature computation logic
- Model inference
- Fallback controller

### Integration Tests
- End-to-end data flow
- Redis feature serving
- Model registry integration
- Alert system

### Performance Tests
- Latency benchmarks
- Throughput testing
- Memory/CPU profiling
- Backpressure handling

## MVP Implementation Order

1. **Minimal Ingestor** (3 days)
   - Single symbol WebSocket connection
   - Basic Avro serialization
   - Console output (no Kinesis yet)

2. **Local Stream Processing** (3 days)
   - Simple VWAP calculation
   - In-memory state (no Redis yet)
   - File-based output

3. **Basic Inference** (2 days)
   - Dummy model (random predictions)
   - Feature mocking
   - Simple risk checks

4. **Integration** (2 days)
   - Connect components
   - Add proper error handling
   - Basic monitoring

## Configuration Management

### Environment-specific configs:
- `config/local.yaml`
- `config/dev.yaml`
- `config/prod.yaml`

### Secrets management:
- Local: `.env` files
- Production: AWS Secrets Manager

## Next Steps for Implementation

1. Set up basic project structure
2. Create Docker Compose for local development
3. Implement minimal ingestor service
4. Add comprehensive testing framework
5. Gradually add complexity following the phases above