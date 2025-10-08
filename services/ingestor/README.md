# Bitcoin Ingestor Service - Dual Mode Architecture

## Overview

The Bitcoin Ingestor Service implements a **dual-mode architecture** for the 10-second ahead Bitcoin price prediction pipeline. It operates two synchronized modes: **SBE streaming** for the hot path and **REST polling** for reliability and gap prevention, ensuring **zero-downtime** operation with **atomic re-anchoring**.

## Architecture Philosophy

- **Hot Path**: SBE WebSocket → Kinesis → Redis (real-time inference, <100ms)
- **Reliability Path**: REST API → Gap Detection → Atomic Re-anchor → S3 Backfill
- **Zero Compromise**: Hot path never waits for REST operations
- **Atomic Recovery**: Re-anchoring uses key swapping, never clears Redis

## Dual-Mode Operation

```
┌─────────────────────────────────────────────────────────────────┐
│                       SBE MODE (Hot Path)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Binance SBE ──► C++ Decoder ──► Kinesis ──► Lambda ──► Redis   │
│  WebSocket    │  (<1ms)       │ Streams   │ /KDA   │ Hot State  │
│               │               │           │        │            │
│               ▼               ▼           ▼        ▼            │
│         ┌──────────┐    ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│         │Trades    │    │market-   │ │Real-time │ │Order Book│ │
│         │Depth     │    │sbe-*     │ │Processing│ │Trade Stats│ │
│         │BestBidAsk│    │streams   │ │          │ │Features  │ │
│         └──────────┘    └──────────┘ └──────────┘ └──────────┘ │
└─────────────────────────────────────────────────────────────────┘
                                   │
┌─────────────────────────────────────────────────────────────────┐
│                    REST MODE (Reliability Path)                 │
├─────────────────────────────────────────────────────────────────┤
│                                   │                             │
│  EventBridge ──► REST Poller ──► Gap Detection ──► Re-anchor    │
│  (1-min)      │                │               │               │
│               │                │               │               │
│               ▼                ▼               ▼               │
│         ┌──────────┐     ┌──────────┐    ┌──────────┐         │
│         │/depth    │     │Sequence  │    │Atomic    │         │
│         │/aggTrades│     │Monitor   │    │Redis Swap│         │
│         │/klines   │     │          │    │          │         │
│         └──────────┘     └──────────┘    └──────────┘         │
│               │                │               │               │
│               ▼                ▼               ▼               │
│         ┌──────────┐     ┌──────────┐    ┌──────────┐         │
│         │S3 Bronze │     │Alert     │    │Resume SBE│         │
│         │Backfill  │     │System    │    │Processing│         │
│         └──────────┘     └──────────┘    └──────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

## Quick Start

### Prerequisites
```bash
# Install dependencies
pip install -r requirements.txt

# Build SBE decoder (required for SBE mode)
chmod +x build_sbe_decoder.sh
./build_sbe_decoder.sh

# Set environment variables
export BINANCE_API_KEY="your_binance_api_key"
export BINANCE_API_SECRET="your_binance_api_secret"
```

### Local Development with Docker Compose

1. **Start Infrastructure**:
```bash
cd ../../  # Project root
docker-compose up localstack redis -d
```

2. **Run SBE Mode (Hot Path)**:
```bash
CONFIG_FILE=config/local.yaml MODE=sbe python src/main.py
```

3. **Run REST Mode (Reliability Path)** (separate terminal):
```bash
CONFIG_FILE=config/local.yaml MODE=rest python src/main.py
```

4. **Check Health**:
```bash
curl http://localhost:8080/health  # SBE service
curl http://localhost:8081/health  # REST service
```

### Production Deployment

```bash
# Build and deploy both modes
docker build -t bitcoin-ingestor .

# SBE mode (hot path)
docker run -d --name ingestor-sbe \
  -p 8080:8080 \
  -e CONFIG_FILE=config/prod.yaml \
  -e MODE=sbe \
  -e BINANCE_API_KEY=${BINANCE_API_KEY} \
  bitcoin-ingestor

# REST mode (reliability path)  
docker run -d --name ingestor-rest \
  -p 8081:8081 \
  -e CONFIG_FILE=config/prod.yaml \
  -e MODE=rest \
  -e BINANCE_API_KEY=${BINANCE_API_KEY} \
  bitcoin-ingestor
```

## Configuration

### SBE Mode Configuration (`config/sbe.yaml`)
```yaml
service_name: "bitcoin-ingestor-sbe"
mode: "sbe"

binance:
  sbe_ws_url: "wss://stream-sbe.binance.com:9443"
  api_key: "${BINANCE_API_KEY}"
  symbols: ["BTCUSDT"]
  stream_types: ["trade", "bestBidAsk", "depth"]
  reconnect_interval_seconds: 5

aws:
  region: "us-east-1"
  kinesis:
    streams:
      trade: "market-sbe-trade"
      bestbidask: "market-sbe-bestbidask"  
      depth: "market-sbe-depth"
    batch_size: 500
    flush_interval_seconds: 1

health:
  port: 8080
  host: "0.0.0.0"

metrics:
  enable_prometheus: true
  prometheus_port: 9090
```

### REST Mode Configuration (`config/rest.yaml`)
```yaml
service_name: "bitcoin-ingestor-rest"
mode: "rest"

binance:
  rest_base_url: "https://data-api.binance.vision"
  symbols: ["BTCUSDT"]
  rate_limit_requests_per_minute: 1200

aws:
  region: "us-east-1"
  s3:
    bucket: "bitcoin-data-lake"
    bronze_prefix: "bronze"

scheduler:
  poll_interval_seconds: 60  # Every 1 minute
  gap_detection_enabled: true
  reanchor_enabled: true

health:
  port: 8081
  host: "0.0.0.0"
```

## SBE Mode (Hot Path)

### Purpose
- **Real-time streaming** for sub-100ms inference pipeline
- **Direct Redis updates** via Kinesis Lambda processors
- **Zero latency compromise** for prediction accuracy

### Key Features
- **C++ SBE Decoder**: Sub-millisecond binary message parsing
- **Kinesis Integration**: Reliable message delivery with Lambda/KDA processing
- **Redis Hot State**: Direct order book and trade statistics updates
- **Sequence Monitoring**: Gap detection for reliability triggers

### Data Flow
```
SBE WebSocket → C++ Decoder → Kinesis Streams → Lambda/KDA → Redis
     ↓              ↓             ↓              ↓         ↓
Trade Events    Binary→JSON   Reliable      Real-time   Hot State
Depth Updates   <1ms parse    Delivery      Processing  Updates
BestBidAsk      Type-safe     Partitioned   Features    ob:BTCUSDT
                Schema        Auto-scale    Compute     tr:BTCUSDT:*
```

### Performance Targets
- **Parse Latency**: <1ms per SBE message
- **End-to-end**: SBE → Redis <50ms (P95)
- **Throughput**: 5,000+ messages/second
- **Availability**: 99.95% uptime (excluding planned maintenance)

### SBE Message Types

#### Trade Events (`trade`)
```json
{
  "symbol": "BTCUSDT",
  "event_ts": 1638360000123456,  // Microsecond precision
  "trade_id": 123456789,
  "price": 45230.50,
  "quantity": 0.1567,
  "is_buyer_maker": false,
  "sequence_id": 987654321,      // For gap detection
  "source": "sbe"
}
```

#### Best Bid/Ask (`bestBidAsk`)
```json
{
  "symbol": "BTCUSDT", 
  "event_ts": 1638360000123456,
  "bid_price": 45229.50,
  "bid_quantity": 1.234,
  "ask_price": 45231.00,
  "ask_quantity": 0.987,
  "sequence_id": 987654322,
  "source": "sbe"
}
```

#### Depth Updates (`depth`)
```json
{
  "symbol": "BTCUSDT",
  "event_ts": 1638360000123456,
  "first_update_id": 123450000,
  "final_update_id": 123450010,
  "bids": [["45229.50", "1.234"], ["45229.00", "2.567"]],
  "asks": [["45231.00", "0.987"], ["45231.50", "1.876"]],
  "source": "sbe"
}
```

## REST Mode (Reliability Path)

### Purpose
- **Gap detection** in SBE stream via sequence monitoring
- **Atomic re-anchoring** to recover Redis state without downtime
- **S3 backfill** for historical analysis and training
- **Validation** of SBE data consistency

### Key Features
- **EventBridge Scheduling**: 1-minute polling for consistency
- **Gap Detection**: Multi-criteria validation (sequence, time, volume)
- **Atomic Re-anchor**: Redis key swapping without clearing state
- **S3 Bronze Layer**: Historical data for training pipeline

### Data Flow
```
EventBridge → REST Poller → Gap Detection → Re-anchor Decision
    ↓             ↓             ↓                ↓
1-min Timer   /depth        Sequence ID      Atomic Redis
Schedule      /aggTrades    Validation       Key Swapping
              /klines       Time Gaps        
                           Volume Check      Resume SBE
```

### REST API Endpoints Used

#### Order Book Snapshot (`/api/v3/depth`)
```bash
GET /api/v3/depth?symbol=BTCUSDT&limit=100
```
Used for: Re-anchoring order book state in Redis

#### Aggregate Trades (`/api/v3/aggTrades`)
```bash
GET /api/v3/aggTrades?symbol=BTCUSDT&fromId=123456&limit=1000
```
Used for: Backfilling trade data and gap detection

#### Klines (`/api/v3/klines`)
```bash
GET /api/v3/klines?symbol=BTCUSDT&interval=1m&limit=60
```
Used for: Validation and S3 bronze layer

### Gap Detection Algorithm

```python
def detect_gap(current_sequence: int, last_sequence: int, 
               current_time: int, last_time: int) -> bool:
    # Sequence gap detection
    sequence_gap = current_sequence - last_sequence > 1
    
    # Time gap detection (>5 seconds)
    time_gap = current_time - last_time > 5_000_000  # microseconds
    
    # Volume consistency check
    volume_inconsistent = check_volume_consistency()
    
    return sequence_gap or time_gap or volume_inconsistent
```

### Atomic Re-anchoring Procedure

```python
async def atomic_reanchor(symbol: str):
    # 1. Set re-anchor flag (prevents concurrent operations)
    await redis.set(f'reanchor:{symbol}', '1', ex=300)
    
    # 2. Fetch fresh data from REST APIs (parallel)
    depth_data, trades_data = await asyncio.gather(
        binance_rest.get_depth(symbol, limit=100),
        binance_rest.get_recent_trades(symbol, limit=1000)
    )
    
    # 3. Build new state in temporary Redis keys
    await build_temp_order_book(f'ob:new:{symbol}', depth_data)
    await build_temp_trade_stats(f'tr:new:{symbol}', trades_data)
    await build_temp_features(f'feat:new:{symbol}')
    
    # 4. Atomic swap (all operations succeed or all fail)
    pipeline = redis.pipeline()
    pipeline.rename(f'ob:new:{symbol}', f'ob:{symbol}')
    pipeline.rename(f'tr:new:{symbol}:1s', f'tr:{symbol}:1s')
    pipeline.rename(f'tr:new:{symbol}:5s', f'tr:{symbol}:5s')
    pipeline.rename(f'feat:new:{symbol}', f'feat:{symbol}')
    pipeline.delete(f'reanchor:{symbol}')
    await pipeline.execute()  # Atomic operation
    
    # 5. Resume SBE processing
    logger.info(f"Re-anchor completed for {symbol}")
```

## Health Monitoring

### SBE Mode Health Checks

```bash
GET /health
{
  "status": "healthy",
  "service": "bitcoin-ingestor-sbe", 
  "components": {
    "sbe_websocket": {
      "status": "connected",
      "last_message_age_ms": 150,
      "messages_per_second": 125.5,
      "reconnect_count": 0
    },
    "kinesis_producer": {
      "status": "healthy",
      "success_rate": 0.999,
      "avg_latency_ms": 15,
      "buffer_size": 45
    },
    "sbe_decoder": {
      "status": "loaded",
      "decode_errors": 0,
      "messages_decoded": 1567890,
      "avg_decode_time_us": 450
    }
  }
}
```

### REST Mode Health Checks

```bash
GET /health
{
  "status": "healthy",
  "service": "bitcoin-ingestor-rest",
  "components": {
    "binance_rest": {
      "status": "healthy",
      "last_call_latency_ms": 85,
      "rate_limit_remaining": 1150,
      "error_rate": 0.001
    },
    "gap_detector": {
      "status": "monitoring", 
      "last_check_time": "2024-01-15T14:30:00Z",
      "gaps_detected_today": 0,
      "last_sequence_id": 987654321
    },
    "s3_writer": {
      "status": "healthy",
      "files_written_today": 24,
      "avg_write_latency_ms": 120,
      "write_errors": 0
    }
  }
}
```

## Performance Metrics

### SBE Mode Metrics
- `ingestor_sbe_messages_total` - Total SBE messages processed
- `ingestor_sbe_decode_duration_seconds` - SBE decode latency histogram
- `ingestor_kinesis_records_sent_total` - Records sent to Kinesis
- `ingestor_sbe_connection_status` - WebSocket connection status
- `ingestor_sbe_sequence_gaps_total` - Detected sequence gaps

### REST Mode Metrics  
- `ingestor_rest_api_calls_total` - REST API calls made
- `ingestor_rest_gaps_detected_total` - Gaps detected
- `ingestor_rest_reanchors_total` - Re-anchor operations performed
- `ingestor_rest_s3_files_written_total` - Files written to S3
- `ingestor_rest_api_latency_seconds` - REST API latency histogram

## Error Handling

### SBE Mode Error Scenarios

#### WebSocket Disconnection
```python
async def handle_websocket_disconnect():
    logger.warning("SBE WebSocket disconnected")
    # Attempt reconnection with exponential backoff
    for attempt in range(MAX_RECONNECT_ATTEMPTS):
        await asyncio.sleep(2 ** attempt)
        if await sbe_client.connect():
            logger.info("SBE reconnection successful")
            return
    
    # If all reconnects fail, alert and degrade gracefully
    logger.error("SBE reconnection failed, entering degraded mode")
    await alert_ops_team("SBE_RECONNECTION_FAILED")
```

#### Kinesis Throttling
```python
async def handle_kinesis_throttling():
    # Exponential backoff with jitter
    await asyncio.sleep(random.uniform(1, 5))
    # Reduce batch size temporarily
    kinesis_producer.reduce_batch_size()
```

### REST Mode Error Scenarios

#### API Rate Limiting
```python
async def handle_rate_limit(retry_after: int):
    logger.warning(f"Binance rate limit hit, waiting {retry_after}s")
    await asyncio.sleep(retry_after)
    # Continue with next scheduled poll
```

#### Re-anchor Failure
```python
async def handle_reanchor_failure(symbol: str, error: Exception):
    logger.error(f"Re-anchor failed for {symbol}: {error}")
    # Clean up temporary keys
    await cleanup_temp_keys(symbol)
    # Clear re-anchor flag
    await redis.delete(f'reanchor:{symbol}')
    # Alert ops team
    await alert_ops_team("REANCHOR_FAILED", symbol=symbol)
```

## Development and Testing

### Local Development Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 2. Build SBE decoder
./build_sbe_decoder.sh

# 3. Start local infrastructure
docker-compose up localstack redis -d

# 4. Set environment variables
export BINANCE_API_KEY="your_test_key"
export AWS_ACCESS_KEY_ID="localstack"
export AWS_SECRET_ACCESS_KEY="localstack"

# 5. Run tests
pytest tests/

# 6. Start services
python src/main.py --mode sbe --config config/local.yaml
python src/main.py --mode rest --config config/local.yaml
```

### Testing Strategy

#### Unit Tests
```bash
# Test SBE decoder
pytest tests/unit/test_sbe_decoder.py

# Test gap detection algorithm  
pytest tests/unit/test_gap_detection.py

# Test atomic re-anchor logic
pytest tests/unit/test_reanchor.py
```

#### Integration Tests
```bash
# Test SBE → Kinesis → Redis flow
pytest tests/integration/test_sbe_pipeline.py

# Test REST → S3 → Re-anchor flow
pytest tests/integration/test_rest_pipeline.py

# Test full dual-mode operation
pytest tests/integration/test_dual_mode.py
```

#### Performance Tests
```bash
# Test SBE decode performance (<1ms requirement)
pytest tests/performance/test_sbe_latency.py

# Test atomic re-anchor speed (<60s requirement)
pytest tests/performance/test_reanchor_speed.py
```

## Troubleshooting

### Common Issues

#### 1. SBE Decoder Build Failure
```bash
# Install build dependencies
sudo apt-get install build-essential cmake python3-dev

# Clean and rebuild
rm -rf sbe_decoder/build/
./build_sbe_decoder.sh
```

#### 2. WebSocket Authentication Failure
```bash
# Verify API key has SBE permissions
curl -H "X-MBX-APIKEY: ${BINANCE_API_KEY}" \
  "https://api.binance.com/api/v3/account"

# Check WebSocket URL and headers
```

#### 3. Redis Connection Issues
```bash
# Check Redis connectivity
redis-cli ping

# Verify Redis configuration
redis-cli config get '*'
```

#### 4. Kinesis Throttling
```bash
# Check shard count
aws kinesis describe-stream --stream-name market-sbe-trade

# Monitor metrics
aws cloudwatch get-metric-statistics \
  --namespace AWS/Kinesis \
  --metric-name IncomingRecords \
  --start-time 2024-01-15T14:00:00Z \
  --end-time 2024-01-15T15:00:00Z \
  --period 300 \
  --statistics Sum
```

### Debugging Commands

```bash
# Monitor SBE messages
curl -s http://localhost:8080/stats | jq '.sbe_stats'

# Check gap detection status
curl -s http://localhost:8081/stats | jq '.gap_detection'

# View recent logs
docker logs bitcoin-ingestor-sbe --tail 100 | jq '.message'

# Monitor Redis keys
redis-cli --scan --pattern "ob:*" | head -10
redis-cli --scan --pattern "tr:*" | wc -l
```

This dual-mode architecture ensures **zero-downtime** Bitcoin price prediction with **sub-100ms inference latency** while maintaining **data integrity** through atomic re-anchoring and gap detection.