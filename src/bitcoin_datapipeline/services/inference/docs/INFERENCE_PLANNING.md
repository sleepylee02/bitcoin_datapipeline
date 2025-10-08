# Bitcoin Price Prediction Inference Service Planning

## Overview

This document outlines how the inference service will consume data from the pipeline to provide real-time Bitcoin price predictions every 1-2 seconds with <100ms latency.

## Data Flow Architecture

```
┌─────────────┐    ┌──────────────┐    ┌─────────────┐
│   Redis     │    │  Inference   │    │ Prediction  │
│ (Features)  │───▶│   Service    │───▶│   Output    │
└─────────────┘    └──────────────┘    └─────────────┘
       ▲                   │
       │                   ▼
┌─────────────┐    ┌──────────────┐
│ Aggregator  │    │  MLP Model   │
│ (Real-time) │    │ (Pre-trained)│
└─────────────┘    └──────────────┘
```

## Raw Data Sources and Transformation Pipeline

### 1. SBE Real-time Data (Primary Pipeline)

#### Original SBE Message Formats

**Trade Data (24@1)**:
```cpp
struct Trade {
    uint64_t timestamp;        // Unix timestamp microseconds
    uint64_t trade_id;
    uint32_t symbol_id;        // BTCUSDT = 1
    double price;              // Trade execution price
    double quantity;           // Trade quantity
    uint8_t is_buyer_maker;    // 1 if buyer is maker
    uint16_t padding;
};
```

**Best Bid/Ask Data (24@2)**:
```cpp
struct BestBidAsk {
    uint64_t timestamp;
    uint32_t symbol_id;
    double bid_price;          // Best bid price
    double bid_quantity;       // Best bid quantity  
    double ask_price;          // Best ask price
    double ask_quantity;       // Best ask quantity
    uint32_t padding;
};
```

**Depth/Order Book Data (24@3)**:
```cpp
struct DepthUpdate {
    uint64_t timestamp;
    uint32_t symbol_id;
    uint64_t first_update_id;
    uint64_t final_update_id;
    uint8_t side;              // 0=bid, 1=ask
    double price;
    double quantity;           // 0 means remove level
    uint8_t padding[7];
};
```

#### SBE → Kinesis Transformation

**SBE Ingestor Processing**:
```python
# Raw SBE binary → JSON for Kinesis
def transform_sbe_to_kinesis(sbe_message: bytes) -> dict:
    decoded = sbe_decoder.decode(sbe_message)
    
    # Trade message transformation
    if decoded.template_id == 1:
        return {
            "message_type": "trade",
            "symbol": "BTCUSDT",
            "timestamp": decoded.timestamp,
            "trade_id": decoded.trade_id,
            "price": decoded.price,
            "quantity": decoded.quantity,
            "is_buyer_maker": decoded.is_buyer_maker,
            "ingest_ts": int(time.time() * 1000),
            "source": "sbe"
        }
    
    # BestBidAsk transformation
    elif decoded.template_id == 2:
        return {
            "message_type": "bestbidask",
            "symbol": "BTCUSDT", 
            "timestamp": decoded.timestamp,
            "bid_price": decoded.bid_price,
            "bid_quantity": decoded.bid_quantity,
            "ask_price": decoded.ask_price,
            "ask_quantity": decoded.ask_quantity,
            "ingest_ts": int(time.time() * 1000),
            "source": "sbe"
        }
```

### 2. Kinesis → Redis Aggregation Pipeline

#### Aggregator Processing Logic

**Input from Kinesis**: Raw SBE-transformed messages
**Output to Redis**: Engineered features for inference

```python
class FeatureAggregator:
    def aggregate_trade_features(self, trades: List[dict]) -> dict:
        """Process trade messages into features"""
        
        # Calculate VWAP (Volume Weighted Average Price)
        total_volume = sum(t['quantity'] for t in trades)
        vwap = sum(t['price'] * t['quantity'] for t in trades) / total_volume
        
        # Price changes
        prices = [t['price'] for t in trades]
        price_change_1m = (prices[-1] - prices[0]) / prices[0]
        
        # Volume metrics
        volume_sum = sum(t['quantity'] for t in trades)
        trade_intensity = len(trades) / time_window_seconds
        
        return {
            "vwap": vwap,
            "price_change_1m": price_change_1m,
            "volume": volume_sum,
            "trade_intensity": trade_intensity,
            "last_price": prices[-1]
        }
    
    def aggregate_orderbook_features(self, book_updates: List[dict]) -> dict:
        """Process order book updates into features"""
        
        latest_book = book_updates[-1]
        
        # Bid-ask spread
        spread = latest_book['ask_price'] - latest_book['bid_price']
        spread_pct = spread / latest_book['bid_price']
        
        # Order book imbalance
        bid_value = latest_book['bid_price'] * latest_book['bid_quantity']
        ask_value = latest_book['ask_price'] * latest_book['ask_quantity'] 
        imbalance = (bid_value - ask_value) / (bid_value + ask_value)
        
        return {
            "bid_ask_spread": spread_pct,
            "order_book_imbalance": imbalance,
            "bid_price": latest_book['bid_price'],
            "ask_price": latest_book['ask_price']
        }
```

#### Final Redis Feature Schema

**Aggregated Features stored in Redis**:
```json
{
  "symbol": "BTCUSDT",
  "timestamp": 1638360000000,
  "price": 45230.50,              // From: latest trade price
  "volume": 123.45,               // From: sum(trade.quantity) in window
  "vwap": 45225.30,              // From: Σ(price*quantity) / Σ(quantity)
  "price_change_1m": 0.02,       // From: (last_price - first_price) / first_price
  "price_change_5m": 0.15,       // From: 5-minute rolling calculation
  "volume_avg_1m": 100.32,       // From: rolling average of volume
  "bid_ask_spread": 0.05,        // From: (ask_price - bid_price) / bid_price
  "order_book_imbalance": 0.12,  // From: (bid_value - ask_value) / total_value
  "trade_intensity": 1.5,        // From: trades_count / time_window
  "rsi_5m": 65.2,               // From: RSI calculation on price series
  "macd_signal": 0.8,           // From: MACD indicator calculation
  "bollinger_position": 0.3     // From: (price - bb_lower) / (bb_upper - bb_lower)
}
```

### 3. REST API Historical Data (Training Pipeline)

#### Original Binance REST Response

**Aggregate Trades (`/api/v3/aggTrades`)**:
```json
[
  {
    "a": 26129,           // Aggregate trade ID
    "p": "0.01633102",    // Price
    "q": "4.70443515",    // Quantity
    "f": 27781,           // First trade ID
    "l": 27781,           // Last trade ID
    "T": 1498793709153,   // Timestamp
    "m": true,            // Was the buyer the market maker?
    "M": true             // Was the trade the best price match?
  }
]
```

**Klines/Candlestick Data (`/api/v3/klines`)**:
```json
[
  [
    1499040000000,      // Open time
    "0.01634790",       // Open
    "0.80000000",       // High
    "0.01575800",       // Low
    "0.01577100",       // Close
    "148976.11427815",  // Volume
    1499644799999,      // Close time
    "2434.19055334",    // Quote asset volume
    308,                // Number of trades
    "1756.87402397",    // Taker buy base asset volume
    "28.46694368",      // Taker buy quote asset volume
    "17928899.62484339" // Ignore
  ]
]
```

#### REST → S3 → PostgreSQL Transformation

**S3 Storage Format (Avro)**:
```json
{
  "symbol": "BTCUSDT",
  "timestamp": 1638360000000,
  "price": 45230.50,
  "volume": 123.45,
  "bid_price": 45229.50,
  "ask_price": 45231.50,
  "source": "rest",
  "data_type": "aggTrades",
  "metadata": {
    "collection_time": 1638360001000,
    "api_latency_ms": 45
  }
}
```

**PostgreSQL Schema**:
```sql
CREATE TABLE market_data (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    timestamp BIGINT NOT NULL,
    price DECIMAL(20,8) NOT NULL,
    volume DECIMAL(20,8),
    bid_price DECIMAL(20,8),
    ask_price DECIMAL(20,8),
    source VARCHAR(10) NOT NULL,
    data_type VARCHAR(20),
    created_at TIMESTAMP DEFAULT NOW()
) PARTITION BY RANGE (timestamp);
```

### 4. Fallback Data Source

#### Direct Binance REST API (When Redis stale)

**Ticker Price (`/api/v3/ticker/price`)**:
```json
{
  "symbol": "BTCUSDT",
  "price": "45230.50000000"
}
```

**24hr Ticker Statistics (`/api/v3/ticker/24hr`)**:
```json
{
  "symbol": "BTCUSDT",
  "priceChange": "-94.99999800",
  "priceChangePercent": "-0.205",
  "weightedAvgPrice": "45230.50000000",
  "prevClosePrice": "46325.49000000",
  "lastPrice": "45230.50000000",
  "bidPrice": "45229.50000000",
  "askPrice": "45231.50000000",
  "volume": "123.45000000"
}
```

#### Fallback Feature Generation
```python
def generate_fallback_features(ticker_data: dict) -> dict:
    """Generate features from REST API when Redis unavailable"""
    
    return {
        "symbol": ticker_data["symbol"],
        "timestamp": int(time.time() * 1000),
        "price": float(ticker_data["lastPrice"]),
        "volume": float(ticker_data["volume"]),
        "vwap": float(ticker_data["weightedAvgPrice"]),
        "price_change_1m": float(ticker_data["priceChangePercent"]) / 100,
        "price_change_5m": 0.0,  # Not available, use default
        "volume_avg_1m": float(ticker_data["volume"]) / 1440,  # Estimate
        "bid_ask_spread": (float(ticker_data["askPrice"]) - float(ticker_data["bidPrice"])) / float(ticker_data["bidPrice"]),
        "order_book_imbalance": 0.0,  # Not available
        "trade_intensity": 0.5,  # Default estimate
        "rsi_5m": 50.0,  # Neutral default
        "macd_signal": 0.0,  # Default
        "bollinger_position": 0.5,  # Neutral default
        "source": "fallback"
    }
```

## Complete Data Transformation Flow

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   SBE Binary    │    │  Kinesis JSON   │    │ Redis Features  │
│                 │    │                 │    │                 │
│ Trade(24@1)     │───▶│ {               │───▶│ {               │
│ BestBidAsk(24@2)│    │   message_type, │    │   vwap,         │
│ Depth(24@3)     │    │   symbol,       │    │   price_change, │
│                 │    │   timestamp,    │    │   volume_avg,   │
│                 │    │   price,        │    │   bid_ask_spread│
│                 │    │   quantity      │    │ }               │
│                 │    │ }               │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         │                       │                       ▼
         │                       │              ┌─────────────────┐
         │                       │              │ Inference Model │
         │                       │              │                 │
         │                       │              │ 12 Features     │
         │                       │              │ ──────────────  │
         │                       │              │ MLP Forward     │
         │                       │              │ Pass <30ms      │
         │                       │              └─────────────────┘
         │                       │                       │
┌─────────────────┐    ┌─────────────────┐               ▼
│ REST API JSON   │    │ S3 Avro Files   │    ┌─────────────────┐
│                 │    │                 │    │ Prediction      │
│ aggTrades       │───▶│ Historical      │    │                 │
│ klines          │    │ Training Data   │    │ {               │
│ ticker/24hr     │    │                 │    │   predicted_price│
│                 │    │                 │    │   confidence,   │
│                 │    │                 │    │   latency_ms    │
│                 │    │                 │    │ }               │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │
         │                       ▼
         │              ┌─────────────────┐
         │              │ PostgreSQL RDBMS│
         │              │                 │
         └──────────────│ Training Data   │
          (Fallback)    │ for Model       │
                        │ Development     │
                        └─────────────────┘
```

## Model Input Requirements

### Feature Engineering Pipeline
1. **Fetch Latest Features**: Get most recent feature set from Redis
2. **Feature Validation**: Ensure all required features are present and valid
3. **Normalization**: Apply pre-computed scaling factors
4. **Sequence Preparation**: Create time-series sequence for LSTM/attention layers

### Required Features (12 inputs)
```python
@dataclass
class ModelInput:
    # Price features
    current_price: float
    price_change_1m: float
    price_change_5m: float
    vwap: float
    
    # Volume features  
    volume: float
    volume_avg_1m: float
    trade_intensity: float
    
    # Order book features
    bid_ask_spread: float
    order_book_imbalance: float
    
    # Technical indicators
    rsi_5m: float
    macd_signal: float
    bollinger_position: float
```

### Sequence Length
- **Primary**: Single point prediction (current features only)
- **Enhanced**: 5-point sequence (last 5 feature updates)
- **Memory**: Store last 10 feature points for sequence building

## Model Architecture

### MLP Configuration
```python
model_config = {
    "input_size": 12,
    "hidden_layers": [64, 32, 16],
    "output_size": 1,
    "activation": "ReLU",
    "dropout": 0.2,
    "batch_norm": True
}
```

### Model Loading Strategy
1. **Startup**: Load pre-trained model from S3/local storage
2. **Caching**: Keep model in memory for <1ms inference
3. **Hot Reload**: Support model updates without service restart
4. **Fallback**: Basic linear regression if main model fails

## Prediction Output

### Output Schema
```python
@dataclass
class PredictionResult:
    symbol: str = "BTCUSDT"
    timestamp: int  # Unix timestamp ms
    current_price: float
    predicted_price: float
    prediction_horizon_seconds: int = 60  # 1-minute ahead
    confidence: float  # 0.0 - 1.0
    model_version: str
    features_age_ms: int  # Age of input features
    inference_latency_ms: int  # Processing time
    source: str = "redis"  # "redis" or "fallback"
```

### Output Destinations
1. **WebSocket**: Real-time client updates
2. **Redis**: Cache latest prediction (key: `prediction:BTCUSDT:latest`)
3. **CloudWatch**: Metrics and monitoring
4. **S3**: Prediction history for model evaluation

## Performance Requirements

### Latency Targets
- **Feature Retrieval**: <10ms (Redis local)
- **Model Inference**: <30ms (MLP forward pass)
- **Output Processing**: <10ms (serialization)
- **Total Target**: <50ms (excluding network)

### Throughput Targets
- **Prediction Frequency**: Every 1-2 seconds
- **Concurrent Requests**: Support 100+ WebSocket connections
- **CPU Usage**: <50% on single core

## Error Handling Strategy

### 1. Stale Features (>5s old)
```python
if feature_age_ms > 5000:
    # Fallback to REST API
    features = await binance_client.get_current_market_data()
    prediction.source = "fallback"
```

### 2. Missing Features
```python
if missing_features:
    # Use last known values with warning
    features = fill_missing_with_last_known(features)
    prediction.confidence *= 0.8  # Reduce confidence
```

### 3. Model Failure
```python
try:
    prediction = model.predict(features)
except Exception:
    # Simple linear extrapolation
    prediction = linear_trend_prediction(price_history)
    prediction.confidence = 0.3
```

### 4. Redis Unavailable
```python
# Direct Binance REST mode
# Increased latency (100-200ms) but service continues
```

## Monitoring and Metrics

### Key Metrics
- **Latency**: P50, P95, P99 inference times
- **Accuracy**: Real-time prediction vs actual price after 1min
- **Availability**: Service uptime percentage
- **Feature Freshness**: Age distribution of input features
- **Prediction Confidence**: Distribution of confidence scores

### Health Checks
- Model loading status
- Redis connectivity
- Feature freshness (<5s)
- Memory usage
- Prediction queue depth

## Configuration Management

### Environment Variables
```yaml
# Model settings
MODEL_PATH: "/app/models/btc_predictor_v1.pkl"
PREDICTION_INTERVAL_SECONDS: 1.5
MAX_FEATURE_AGE_MS: 5000

# Redis settings  
REDIS_HOST: "localhost"
REDIS_FEATURES_KEY_PREFIX: "features"
REDIS_PREDICTION_KEY: "prediction:BTCUSDT:latest"

# Performance settings
MAX_CONCURRENT_PREDICTIONS: 10
FEATURE_CACHE_SIZE: 100
MODEL_BATCH_SIZE: 1
```

## Development Phases

### Phase 1: Basic MLP Inference
- Single-point feature input
- Redis feature consumption
- Simple MLP model
- Basic error handling

### Phase 2: Enhanced Features  
- Sequence-based input (5 points)
- Advanced feature engineering
- Model hot-reloading
- Comprehensive monitoring

### Phase 3: Production Optimization
- Multi-model ensemble
- Advanced fallback strategies
- Auto-scaling capabilities
- A/B testing framework

## Data Dependencies

### From Aggregator Service
- Real-time feature updates in Redis
- Feature schema compatibility
- TTL coordination
- Error state propagation

### From Training Pipeline  
- Model artifacts in S3
- Feature scaling parameters
- Model metadata and versioning
- Performance benchmarks

### External Dependencies
- Binance REST API (fallback)
- CloudWatch (metrics)
- Health check endpoints
- WebSocket client management

## Testing Strategy

### Unit Tests
- Feature validation logic
- Model loading and inference
- Error handling scenarios
- Configuration parsing

### Integration Tests
- Redis feature consumption
- Model prediction accuracy
- End-to-end latency
- Fallback mechanism validation

### Load Tests
- Concurrent prediction requests
- Memory usage under load
- Redis connection pooling
- WebSocket scaling limits