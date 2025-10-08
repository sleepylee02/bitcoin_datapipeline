# Bitcoin Inference Service - Redis-Only Hot Path

## Overview

The Bitcoin Inference Service is the **real-time prediction engine** that generates Bitcoin price predictions **10 seconds ahead** with **2-second frequency** and **sub-100ms latency**. It implements a pure Redis hot path design, reading only from Redis state to ensure consistent performance without I/O dependencies.

## Architecture Philosophy

- **Hot Path Isolation**: Only Redis reads, never REST API or S3 operations
- **Sub-100ms Latency**: P99 inference latency under 100ms requirement
- **2-Second Frequency**: Predictions generated exactly every 2 seconds
- **10-Second Target**: All predictions forecast price 10 seconds ahead
- **Zero Dependencies**: Inference continues even during re-anchoring operations

## Service Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    INFERENCE HOT PATH                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Redis State ──► Feature Read ──► MLP Model ──► 10s Prediction │
│  (hot cache)  │  (<5ms)        │  (<30ms)    │  (every 2s)     │
│               │                │             │                  │
│               ▼                ▼             ▼                  │
│         ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│         │Order Books   │ │Feature       │ │Lightweight   │     │
│         │Trade Stats   │ │Validation    │ │MLP          │     │
│         │Features      │ │& Freshness   │ │<100ms       │     │
│         └──────────────┘ └──────────────┘ └──────────────┘     │
│               │                │             │                  │
│               ▼                ▼             ▼                  │
│         ┌──────────────┐ ┌──────────────┐ ┌──────────────┐     │
│         │<1ms Read     │ │Graceful      │ │Confidence    │     │
│         │Operations    │ │Degradation   │ │Calibration   │     │
│         └──────────────┘ └──────────────┘ └──────────────┘     │
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
export MODEL_PATH="/app/models/btc_predictor_v1.onnx"
```

### Local Development with Docker Compose

1. **Start Infrastructure**:
```bash
cd ../../  # Project root
docker-compose up localstack redis -d
```

2. **Run Inference Service**:
```bash
CONFIG_FILE=config/local.yaml python src/main.py
```

3. **Test Predictions**:
```bash
curl http://localhost:8083/predict
curl http://localhost:8083/health
```

### Production Deployment

```bash
# Build and deploy
docker build -t bitcoin-inference .

docker run -d --name inference \
  -p 8083:8083 \
  -e CONFIG_FILE=config/prod.yaml \
  -e REDIS_HOST=${REDIS_HOST} \
  -e MODEL_PATH=/app/models/btc_predictor_v1.onnx \
  bitcoin-inference
```

## Configuration

### Inference Configuration (`config/inference.yaml`)
```yaml
service_name: "bitcoin-inference"

prediction:
  target_horizon_seconds: 10      # Predict 10 seconds ahead
  frequency_seconds: 2           # Generate predictions every 2 seconds
  max_feature_age_seconds: 5     # Maximum stale feature tolerance
  confidence_threshold: 0.1      # Minimum confidence for valid prediction

model:
  path: "/app/models/btc_predictor_v1.onnx"
  format: "onnx"                 # Support ONNX for optimized inference
  input_features: 18             # Number of input features
  batch_size: 1                  # Single prediction mode
  warm_up_iterations: 100        # Model warm-up for consistent latency

redis:
  host: "localhost"
  port: 6379
  cluster_mode: false
  connection_pool_size: 5        # Small pool for hot path
  socket_timeout_seconds: 0.1    # Fast timeout for hot path
  socket_connect_timeout_seconds: 0.5
  max_retries: 1                 # Minimal retries for latency

performance:
  max_inference_latency_ms: 100  # Hard latency limit
  feature_cache_size: 10         # Cache last N feature sets
  prediction_cache_ttl_seconds: 60
  memory_limit_mb: 512           # Lightweight service

health:
  port: 8083
  host: "0.0.0.0"

metrics:
  enable_prometheus: true
  prometheus_port: 9092
```

## Prediction Pipeline

### 1. Feature Extraction (Every 2 Seconds)

#### Redis Hot State Reading
```python
async def extract_features(symbol: str) -> FeatureVector:
    """Extract features from Redis hot state with <5ms target"""
    
    start_time = time.perf_counter()
    
    # Parallel Redis reads for minimal latency
    order_book, trade_stats_1s, trade_stats_5s, features = await asyncio.gather(
        redis.hgetall(f"ob:{symbol}"),
        redis.hgetall(f"tr:{symbol}:1s"),
        redis.hgetall(f"tr:{symbol}:5s"),
        redis.hgetall(f"feat:{symbol}")
    )
    
    # Validate feature freshness
    feature_age = time.time() - float(features.get("feature_ts", 0))
    if feature_age > MAX_FEATURE_AGE_SECONDS:
        raise StaleFeatureError(f"Features too old: {feature_age}s")
    
    # Build feature vector
    feature_vector = FeatureVector(
        # Price features
        price=float(features["price"]),
        mid_price=float(features["mid_price"]),
        ret_1s=float(features["ret_1s"]),
        ret_5s=float(features["ret_5s"]),
        ret_10s=float(features["ret_10s"]),
        
        # Volume features
        volume_1s=float(features["volume_1s"]),
        volume_5s=float(features["volume_5s"]),
        vol_imbalance_1s=float(features["vol_imbalance_1s"]),
        vol_imbalance_5s=float(features["vol_imbalance_5s"]),
        
        # Order book features
        spread_bp=float(features["spread_bp"]),
        ob_imbalance=float(features["ob_imbalance"]),
        bid_strength=float(features["bid_strength"]),
        ask_strength=float(features["ask_strength"]),
        
        # Trade flow features
        trade_intensity_1s=float(features["trade_intensity_1s"]),
        avg_trade_size_1s=float(features["avg_trade_size_1s"]),
        dollar_volume_1s=float(features["dollar_volume_1s"]),
        
        # Technical indicators
        vwap_dev_1s=float(features["vwap_dev_1s"]),
        vwap_dev_5s=float(features["vwap_dev_5s"]),
        price_volatility=float(features["price_volatility"]),
        momentum=float(features["momentum"]),
        
        # Metadata
        timestamp=int(features["feature_ts"]),
        data_age_ms=int(feature_age * 1000),
        completeness=float(features["completeness"])
    )
    
    read_latency = (time.perf_counter() - start_time) * 1000
    logger.debug(f"Feature extraction completed in {read_latency:.2f}ms")
    
    return feature_vector
```

### 2. Model Inference

#### Lightweight MLP Inference
```python
class BitcoinPricePredictor:
    def __init__(self, model_path: str):
        self.model_path = model_path
        self.session = None
        self.input_name = None
        self.output_name = None
        self.scaler = None
        self.load_model()
    
    def load_model(self):
        """Load ONNX model for optimized inference"""
        import onnxruntime as ort
        
        # Load ONNX model with optimization
        self.session = ort.InferenceSession(
            self.model_path,
            providers=['CPUExecutionProvider'],
            sess_options=self._get_session_options()
        )
        
        # Get input/output tensor names
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        
        # Load feature scaler
        self.scaler = joblib.load(f"{os.path.dirname(self.model_path)}/scaler.pkl")
        
        # Warm up model
        self._warm_up_model()
    
    def predict(self, features: FeatureVector) -> float:
        """Predict Bitcoin price 10 seconds ahead"""
        
        start_time = time.perf_counter()
        
        # Convert features to numpy array
        feature_array = np.array([
            features.price, features.mid_price, features.ret_1s, features.ret_5s,
            features.ret_10s, features.volume_1s, features.volume_5s,
            features.vol_imbalance_1s, features.vol_imbalance_5s,
            features.spread_bp, features.ob_imbalance, features.bid_strength,
            features.ask_strength, features.trade_intensity_1s,
            features.avg_trade_size_1s, features.dollar_volume_1s,
            features.vwap_dev_1s, features.vwap_dev_5s,
            features.price_volatility, features.momentum
        ]).reshape(1, -1).astype(np.float32)
        
        # Apply feature scaling
        scaled_features = self.scaler.transform(feature_array)
        
        # Model inference
        prediction = self.session.run(
            [self.output_name],
            {self.input_name: scaled_features}
        )[0][0]
        
        inference_latency = (time.perf_counter() - start_time) * 1000
        logger.debug(f"Model inference completed in {inference_latency:.2f}ms")
        
        return float(prediction)
    
    def _warm_up_model(self):
        """Warm up model with dummy predictions for consistent latency"""
        dummy_features = np.random.random((1, 20)).astype(np.float32)
        
        for _ in range(100):
            self.session.run([self.output_name], {self.input_name: dummy_features})
```

### 3. Prediction Generation

#### Main Prediction Loop
```python
class PredictionEngine:
    def __init__(self, config, model, redis_client):
        self.config = config
        self.model = model
        self.redis = redis_client
        self.prediction_cache = {}
        self.running = False
    
    async def start_prediction_loop(self):
        """Main prediction loop - generates predictions every 2 seconds"""
        
        self.running = True
        
        while self.running:
            try:
                prediction_start = time.time()
                
                # Generate prediction
                prediction = await self.generate_prediction("BTCUSDT")
                
                # Cache prediction
                await self.cache_prediction(prediction)
                
                # Calculate timing
                total_latency = (time.time() - prediction_start) * 1000
                
                # Log performance
                logger.info(f"Prediction generated: {prediction.predicted_price:.2f} "
                           f"(confidence: {prediction.confidence:.3f}, "
                           f"latency: {total_latency:.1f}ms)")
                
                # Sleep until next prediction time
                sleep_time = max(0, 2.0 - (time.time() - prediction_start))
                await asyncio.sleep(sleep_time)
                
            except Exception as e:
                logger.error(f"Prediction loop error: {e}")
                await asyncio.sleep(1)  # Brief pause on error
    
    async def generate_prediction(self, symbol: str) -> PredictionResult:
        """Generate single prediction with full error handling"""
        
        prediction_start = time.time()
        
        try:
            # 1. Extract features from Redis
            features = await extract_features(symbol)
            
            # 2. Model inference
            predicted_price = self.model.predict(features)
            
            # 3. Calculate confidence
            confidence = self.calculate_confidence(features, predicted_price)
            
            # 4. Build prediction result
            prediction = PredictionResult(
                symbol=symbol,
                timestamp=int(time.time() * 1000),
                current_price=features.price,
                predicted_price=predicted_price,
                prediction_horizon_seconds=10,
                confidence=confidence,
                model_version=self.model.version,
                features_age_ms=features.data_age_ms,
                inference_latency_ms=int((time.time() - prediction_start) * 1000),
                source="redis"
            )
            
            return prediction
            
        except StaleFeatureError:
            # Graceful degradation with lower confidence
            return await self.generate_fallback_prediction(symbol, "stale_features")
            
        except Exception as e:
            logger.error(f"Prediction generation failed: {e}")
            return await self.generate_fallback_prediction(symbol, "error")
    
    def calculate_confidence(self, features: FeatureVector, prediction: float) -> float:
        """Calculate prediction confidence based on feature quality"""
        
        base_confidence = 0.8
        
        # Reduce confidence for stale features
        if features.data_age_ms > 2000:
            base_confidence *= 0.9
        
        # Reduce confidence for incomplete features
        base_confidence *= features.completeness
        
        # Reduce confidence for high volatility
        if features.price_volatility > 0.01:
            base_confidence *= 0.85
        
        # Reduce confidence for wide spreads
        if features.spread_bp > 10:
            base_confidence *= 0.9
        
        return max(0.1, min(1.0, base_confidence))
```

### 4. Fallback and Error Handling

#### Graceful Degradation Strategy
```python
async def generate_fallback_prediction(self, symbol: str, reason: str) -> PredictionResult:
    """Generate fallback prediction when normal pipeline fails"""
    
    try:
        if reason == "stale_features":
            # Use last cached features with degraded confidence
            last_prediction = self.prediction_cache.get(symbol)
            if last_prediction and time.time() - last_prediction.timestamp/1000 < 30:
                # Linear extrapolation
                price_trend = (last_prediction.predicted_price - last_prediction.current_price) / 10
                predicted_price = last_prediction.predicted_price + price_trend * 2
                
                return PredictionResult(
                    symbol=symbol,
                    timestamp=int(time.time() * 1000),
                    current_price=last_prediction.current_price,
                    predicted_price=predicted_price,
                    prediction_horizon_seconds=10,
                    confidence=0.3,
                    model_version=f"{self.model.version}-fallback",
                    features_age_ms=30000,
                    inference_latency_ms=5,
                    source="fallback-stale"
                )
        
        # Default fallback - no prediction
        return PredictionResult(
            symbol=symbol,
            timestamp=int(time.time() * 1000),
            current_price=0.0,
            predicted_price=0.0,
            prediction_horizon_seconds=10,
            confidence=0.0,
            model_version=f"{self.model.version}-error",
            features_age_ms=0,
            inference_latency_ms=1,
            source="fallback-error"
        )
        
    except Exception as e:
        logger.error(f"Fallback prediction failed: {e}")
        return self._emergency_prediction(symbol)
```

## Prediction Caching and Distribution

### 1. Redis Prediction Cache

#### Latest Prediction Caching
```python
async def cache_prediction(self, prediction: PredictionResult):
    """Cache latest prediction in Redis for client access"""
    
    prediction_data = {
        "predicted_price": str(prediction.predicted_price),
        "current_price": str(prediction.current_price),
        "confidence": str(prediction.confidence),
        "prediction_ts": str(prediction.timestamp),
        "target_ts": str(prediction.timestamp + 10000),  # 10s ahead
        "model_version": prediction.model_version,
        "latency_ms": str(prediction.inference_latency_ms),
        "features_age_ms": str(prediction.features_age_ms),
        "source": prediction.source
    }
    
    # Cache with 60-second TTL
    await self.redis.hset(f"pred:{prediction.symbol}", mapping=prediction_data)
    await self.redis.expire(f"pred:{prediction.symbol}", 60)
```

### 2. WebSocket Distribution

#### Real-time Client Updates
```python
class WebSocketManager:
    def __init__(self):
        self.connections = set()
    
    async def broadcast_prediction(self, prediction: PredictionResult):
        """Broadcast prediction to all connected clients"""
        
        if not self.connections:
            return
        
        message = {
            "type": "prediction",
            "data": {
                "symbol": prediction.symbol,
                "timestamp": prediction.timestamp,
                "current_price": prediction.current_price,
                "predicted_price": prediction.predicted_price,
                "confidence": prediction.confidence,
                "latency_ms": prediction.inference_latency_ms
            }
        }
        
        # Broadcast to all connections
        disconnected = set()
        for websocket in self.connections:
            try:
                await websocket.send_text(json.dumps(message))
            except:
                disconnected.add(websocket)
        
        # Clean up disconnected clients
        self.connections -= disconnected
```

## Performance Monitoring

### Health Check Endpoint
```bash
GET /health
{
  "status": "healthy",
  "service": "bitcoin-inference",
  "components": {
    "model": {
      "status": "loaded",
      "version": "v1.2.3",
      "last_prediction": "2024-01-15T14:30:00Z",
      "avg_inference_ms": 25.3,
      "predictions_per_minute": 30
    },
    "redis_connection": {
      "status": "connected",
      "avg_read_latency_ms": 0.8,
      "feature_freshness_ms": 1200,
      "connection_pool_usage": 0.4
    },
    "prediction_pipeline": {
      "status": "active",
      "frequency_actual": 2.0,
      "frequency_target": 2.0,
      "avg_total_latency_ms": 45.2,
      "success_rate": 0.995
    },
    "feature_quality": {
      "avg_completeness": 0.98,
      "avg_data_age_ms": 1500,
      "stale_feature_rate": 0.02
    }
  }
}
```

## Key Metrics

### Latency Metrics
- `inference_total_latency_seconds` - End-to-end prediction latency histogram
- `inference_redis_read_duration_seconds` - Redis feature read time
- `inference_model_prediction_duration_seconds` - Model inference time
- `inference_feature_age_seconds` - Age of input features

### Accuracy Metrics
- `inference_predictions_total` - Total predictions generated
- `inference_confidence_score` - Prediction confidence distribution
- `inference_fallback_predictions_total` - Fallback predictions used
- `inference_feature_completeness` - Feature quality metrics

### Performance Targets
```
Component                        Target    P99 Max
────────────────────────────────────────────────
Redis Feature Read              < 5ms     < 10ms
Model Inference                 < 30ms    < 50ms
Total Prediction Latency        < 50ms    < 100ms
Prediction Frequency            2.0s      ±0.1s
Feature Freshness               < 2s      < 5s
```

## Error Handling Scenarios

### 1. Redis Connection Loss
```python
# Immediate degradation to emergency mode
# Stop predictions rather than block on reconnection
# Alert operations team for manual intervention
```

### 2. Stale Features (>5s old)
```python
# Use last cached prediction with linear extrapolation
# Reduce confidence score significantly
# Continue service with degraded accuracy
```

### 3. Model Loading Failure
```python
# Attempt model reload from backup location
# If failed, use simple linear trend prediction
# Set confidence to minimum (0.1)
```

### 4. Memory Pressure
```python
# Clear prediction cache
# Reduce feature cache size
# Trigger garbage collection
# Alert if memory usage >80%
```

## Testing Strategy

### Unit Tests
```bash
# Test feature extraction
pytest tests/unit/test_feature_extraction.py

# Test model inference
pytest tests/unit/test_model_prediction.py

# Test error handling
pytest tests/unit/test_error_scenarios.py
```

### Integration Tests
```bash
# Test Redis → Prediction pipeline
pytest tests/integration/test_prediction_pipeline.py

# Test WebSocket distribution
pytest tests/integration/test_websocket_broadcast.py

# Test fallback mechanisms
pytest tests/integration/test_fallback_prediction.py
```

### Performance Tests
```bash
# Test latency requirements (<100ms)
pytest tests/performance/test_prediction_latency.py

# Test frequency accuracy (2-second intervals)
pytest tests/performance/test_prediction_frequency.py

# Test concurrent prediction load
pytest tests/performance/test_concurrent_predictions.py
```

## Development Guidelines

### Hot Path Requirements
1. **Redis Only**: No external API calls during normal operation
2. **Minimal Dependencies**: Keep service lightweight and fast
3. **Error Isolation**: Graceful degradation without service interruption
4. **Latency First**: Optimize for speed over additional features
5. **Monitoring**: Comprehensive metrics for all performance aspects

### Code Quality Standards
- Type hints for all function parameters and returns
- Async/await for all I/O operations
- Prometheus metrics for all critical paths
- Structured logging with latency tracking
- Error handling with specific fallback strategies

This inference service ensures reliable 10-second ahead Bitcoin price predictions with sub-100ms latency through Redis-only hot path design and comprehensive fallback mechanisms.