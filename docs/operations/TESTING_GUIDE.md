# Bitcoin Pipeline - Testing Guide

This guide explains how to test the ingestor services step by step using the dedicated `test/` directory.

## Overview

The Bitcoin Pipeline has two main ingestor services:
- **REST Ingestor**: Collects historical data via Binance REST API
- **SBE Ingestor**: Streams real-time data via Binance SBE WebSocket

All testing is organized in the `test/` directory for easy development and CI/CD integration.

## Prerequisites

- Python 3.8+
- Docker & Docker Compose
- Binance API Key (for SBE streams)
- Build tools (gcc, cmake) for SBE decoder

## Quick Start

```bash
# Setup test environment
cd test/
./scripts/setup-test-env.sh

# Edit .env with your Binance API credentials
cp .env.template .env
# Edit .env file

# Run all tests
./scripts/run-all-tests.sh
```

## Testing Phases

### Phase 1: Unit Testing (No Dependencies)

Test individual components in isolation.

#### 1.1 Test REST Client

```bash
cd test/
python unit/test_rest_client.py
```

**What it tests:**
- Binance REST API connectivity
- aggTrades endpoint
- klines endpoint  
- depth (order book) endpoint
- Backfill functionality

**Expected output:**
```
🧪 Bitcoin Pipeline - REST Client Test
==================================================
🔧 Testing Binance REST Client
📡 Endpoint: https://data-api.binance.vision

1️⃣ Testing aggTrades endpoint...
✅ Got 5 aggTrades
   Latest trade: 45230.50 @ 1638360000

2️⃣ Testing klines endpoint...
✅ Got 3 klines
   Latest kline close: 45225.30

3️⃣ Testing depth snapshot...
✅ Got depth with 5 bids, 5 asks
   Best bid: 45229.50
   Best ask: 45230.50

4️⃣ Testing backfill (5 minutes of data)...
✅ Backfill working, got 10 trades

🎉 All REST client tests passed!
✅ REST client is working correctly!
```

#### 1.2 Test SBE Client

The SBE decoder is built automatically during test setup. Test the SBE client:

```bash
cd test/
python unit/test_sbe_client.py
```

Note: Ensure your Binance API credentials are set in `test/.env`

**What it tests:**
- C++ SBE decoder availability
- Binance SBE WebSocket connection
- Message reception and parsing
- Client statistics

**Expected output:**
```
🧪 Bitcoin Pipeline - SBE Client Test
==================================================
Phase 1: SBE Decoder Test
🔧 Testing SBE Decoder Only
✅ C++ SBE decoder loaded successfully
✅ Decoder validation works (dummy result: False)

Phase 2: Full SBE Client Test
🔧 Testing Binance SBE Client
📡 Endpoint: wss://stream-sbe.binance.com:9443
🔑 API Key: your_key...

1️⃣ Checking SBE decoder...
✅ C++ SBE decoder is available

2️⃣ Testing WebSocket connection...
✅ Connected to Binance SBE WebSocket

3️⃣ Testing message reception (10 seconds)...
   📨 trade: BTCUSDT @ 1638360000
   📨 bestBidAsk: BTCUSDT @ 1638360001
   📨 depth: BTCUSDT @ 1638360002
✅ Received 10 messages
   Message types: ['trade', 'bestBidAsk', 'depth']

4️⃣ Checking client statistics...
✅ Stats: 10 received, 10 processed
   Decode errors: 0
   Connections: 1

🎉 All SBE client tests passed!
✅ SBE client is working correctly!
```

### Phase 2: Integration Testing (With Local Dependencies)

Test the complete services with minimal dependencies.

#### 2.1 Test Full Services

```bash
cd test/
python integration/test_full_services.py
```

**What it tests:**
- Service initialization
- Configuration loading
- Health check endpoints
- Service startup/shutdown

### Phase 3: End-to-End Testing (Complete Docker Environment)

Test with full Docker infrastructure and data flow.

#### 3.1 Start Infrastructure

```bash
cd test/
docker-compose -f docker-compose.test.yml up -d
```

This starts:
- LocalStack (S3, Kinesis)
- Redis
- PostgreSQL
- REST Ingestor
- SBE Ingestor
- Aggregator

#### 3.2 Setup LocalStack Resources

```bash
cd test/
./scripts/setup-localstack.sh
```

#### 3.3 Run End-to-End Tests

```bash
cd test/
python e2e/test_pipeline.py
```

**What it tests:**
- Service health endpoints
- AWS infrastructure (Kinesis, S3, Redis)
- Complete data flow
- Data persistence

#### 3.4 Manual Verification

```bash
# Check all services are healthy
cd test/
docker-compose -f docker-compose.test.yml ps

# Check health endpoints
curl http://localhost:8080/health  # REST ingestor
curl http://localhost:8081/health  # SBE ingestor
curl http://localhost:8082/health  # Aggregator

# View logs
docker-compose -f docker-compose.test.yml logs -f rest-ingestor
```

## Troubleshooting

### Common Issues

#### SBE Decoder Build Fails
```bash
# Install build dependencies
sudo apt-get update
sudo apt-get install build-essential cmake python3-dev

# Rebuild decoder
cd services/sbe-ingestor
rm -rf sbe_decoder/build
./build_sbe_decoder.sh
```

#### WebSocket Connection Issues
- Check API key is valid and has permissions
- Verify network connectivity to `stream-sbe.binance.com:9443`
- Check firewall settings

#### LocalStack Issues
```bash
# Reset LocalStack
docker-compose -f docker-compose.test.yml down
rm -rf tmp/localstack
docker-compose -f docker-compose.test.yml up -d localstack
```

#### Permission Issues
```bash
# Fix script permissions
chmod +x scripts/*.sh
chmod +x test_*.py
```

### Test Data Validation

#### REST Ingestor Output
Check `test-data/` directory for JSON files:
```bash
ls -la test-data/
cat test-data/BTCUSDT_aggTrades_*.json | head -5
```

#### SBE Ingestor Output
Check Kinesis streams:
```bash
aws --endpoint-url=http://localhost:4566 kinesis list-streams --region us-east-1
```

## Performance Monitoring

### Key Metrics to Watch

1. **Message Throughput**
   - REST: aggTrades per minute
   - SBE: Messages per second

2. **Latency**
   - End-to-end ingestion time
   - SBE message decode time

3. **Error Rates**
   - API rate limit hits
   - WebSocket disconnections
   - Decode failures

4. **Resource Usage**
   - CPU usage during processing
   - Memory consumption
   - Network bandwidth

## Next Steps

After local testing succeeds:
1. Deploy to AWS EC2 (see AWS_DEPLOYMENT_GUIDE.md)
2. Configure production monitoring
3. Set up alerting
4. Scale based on load requirements

## Test Directory Structure

```
test/
├── unit/
│   ├── test_rest_client.py     # Direct REST client test
│   └── test_sbe_client.py      # Direct SBE client test
├── integration/
│   └── test_full_services.py   # Complete service test
├── e2e/
│   └── test_pipeline.py        # End-to-end pipeline test
├── configs/
│   ├── rest-local.yaml         # REST test configuration
│   └── sbe-local.yaml          # SBE test configuration
├── scripts/
│   ├── setup-test-env.sh       # Environment setup
│   ├── setup-localstack.sh     # LocalStack resource creation
│   └── run-all-tests.sh        # Test runner
├── docker-compose.test.yml     # Docker test environment
└── .env.template               # Environment variables template
```

## File Reference

- `test/unit/test_rest_client.py` - REST client direct test
- `test/unit/test_sbe_client.py` - SBE client direct test  
- `test/integration/test_full_services.py` - Complete service test
- `test/e2e/test_pipeline.py` - End-to-end pipeline test
- `test/docker-compose.test.yml` - Docker test environment
- `test/scripts/setup-test-env.sh` - Environment setup
- `test/scripts/run-all-tests.sh` - Test runner