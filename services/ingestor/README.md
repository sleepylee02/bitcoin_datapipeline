# Bitcoin Ingestor Service

A high-performance, AWS-native service for ingesting Bitcoin market data from Binance, designed for real-time trading pipelines.

## Features

- **Dual Mode Operation**: REST API backfill and real-time SBE WebSocket streaming
- **AWS Native**: Built for Kinesis Data Streams, S3, and CloudWatch
- **Fault Tolerant**: Circuit breakers, exponential backoff, auto-reconnection
- **Monitoring**: Health checks, Prometheus metrics, CloudWatch integration
- **Deduplication**: Prevents duplicate data ingestion
- **Resumable**: REST backfill can resume from checkpoints

## Architecture

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│ Binance API     │    │ Bitcoin Ingestor │    │ AWS Services    │
│                 │    │                  │    │                 │
│ • REST API      │───▶│ • REST Client    │───▶│ • S3 (Bronze)   │
│ • SBE WebSocket │    │ • SBE Client     │    │ • Kinesis       │
│ • Rate Limits   │    │ • Deduplication  │    │ • CloudWatch    │
└─────────────────┘    │ • Health Checks  │    └─────────────────┘
                       └──────────────────┘
```

## Quick Start

### Local Development with Docker Compose

1. **Start LocalStack**:
```bash
docker-compose up localstack redis -d
```

2. **Install Dependencies**:
```bash
pip install -r requirements-dev.txt
```

3. **Run Service**:
```bash
CONFIG_FILE=config/local.yaml python src/main.py
```

4. **Check Health**:
```bash
curl http://localhost:8080/health
```

### Docker Build and Run

```bash
# Build image (includes C++ SBE decoder compilation)
docker build -t bitcoin-ingestor .

# Run container with SBE mode
docker run -p 8080:8080 -p 8081:8081 \
  -e CONFIG_FILE=config/local.yaml \
  -e BINANCE_API_KEY=your_api_key \
  bitcoin-ingestor
```

## Configuration

The service supports environment-specific configuration files:

- `config/local.yaml` - Local development with LocalStack
- `config/dev.yaml` - Development environment
- `config/prod.yaml` - Production configuration

### Setup Configuration

The YAML configuration files use environment variable substitution for secrets. This follows industry best practices for production deployments.

**Required Environment Variables:**
```bash
# Binance API credentials (required for SBE mode)
export BINANCE_API_KEY="your_binance_api_key"
export BINANCE_API_SECRET="your_binance_api_secret"

# AWS credentials (use IAM roles in production, env vars for local/dev)
export AWS_ACCESS_KEY_ID="your_aws_access_key"
export AWS_SECRET_ACCESS_KEY="your_aws_secret_key"
```

**Quick Setup:**
1. Set environment variables (see above)
2. Choose config file: `CONFIG_FILE=config/local.yaml`
3. Run service: `python src/main.py`

**For Local Development:**
```bash
# LocalStack uses default credentials
export AWS_ACCESS_KEY_ID="localstack"
export AWS_SECRET_ACCESS_KEY="localstack"
export BINANCE_API_KEY="your_binance_key"
export BINANCE_API_SECRET="your_binance_secret"

CONFIG_FILE=config/local.yaml python src/main.py
```

**Environment File (Optional):**
Create `.env` file for convenience (not tracked in git):
```bash
# .env
BINANCE_API_KEY=your_binance_api_key
BINANCE_API_SECRET=your_binance_api_secret
AWS_ACCESS_KEY_ID=your_aws_access_key
AWS_SECRET_ACCESS_KEY=your_aws_secret_key
```

Load with: `source .env` or use python-dotenv

### Key Settings

```yaml
# Service mode
mode: "sbe"  # Options: rest, sbe, both

# Binance configuration
binance:
  symbols: ["BTCUSDT"]
  rate_limit_requests_per_minute: 1200

# AWS configuration
aws:
  region: "us-east-1"
  kinesis_trade_stream: "market-sbe-trade"
  s3_bucket: "bitcoin-data-lake"
  localstack_endpoint: "http://localhost:4566"  # For local dev
```

## Operation Modes

### SBE Mode (Real-time Streaming)
- Connects to Binance SBE WebSocket (wss://stream-sbe.binance.com:9443)
- Uses C++ decoder for high-performance binary parsing
- Processes `trade`, `bestBidAsk`, and `depth` messages
- Publishes to Kinesis Data Streams
- Sub-millisecond parsing latency
- Requires Binance API key authentication

### REST Mode (Historical Backfill)
- Fetches historical data via REST API
- Supports `aggTrades`, `trades`, `klines`
- Writes to S3 Bronze layer
- Resumable with checkpoints

### Both Mode
- Runs REST and SBE simultaneously
- Useful for initial backfill + live streaming

## Data Schemas

### Trade Data (Avro)
```json
{
  "symbol": "BTCUSDT",
  "event_ts": 1640995200000,
  "ingest_ts": 1640995200100,
  "trade_id": 12345,
  "price": 45000.50,
  "qty": 0.1,
  "is_buyer_maker": false,
  "source": "sbe"
}
```

### Best Bid/Ask (Avro)
```json
{
  "symbol": "BTCUSDT",
  "event_ts": 1640995200000,
  "ingest_ts": 1640995200100,
  "bid_px": 44999.99,
  "bid_sz": 0.5,
  "ask_px": 45000.01,
  "ask_sz": 0.3,
  "source": "sbe"
}
```

## Monitoring

### Health Endpoints

- `GET /health` - Basic health check
- `GET /health/detailed` - Detailed component status
- `GET /health/components/{component}` - Component-specific health
- `GET /stats` - Service statistics

### Prometheus Metrics

Available on port 8081 (when enabled):

- `ingestor_messages_total` - Total messages processed
- `ingestor_errors_total` - Total errors by component
- `ingestor_kinesis_records_total` - Records sent to Kinesis
- `ingestor_connection_status` - Connection status by component

### CloudWatch Metrics

Automatic emission to CloudWatch (when enabled):

- `MessagesProcessed` - Total messages processed
- `RecordsSentKinesis` - Records sent to Kinesis streams
- `RecordsWrittenS3` - Records written to S3
- `SBEConnectionStatus` - WebSocket connection status

## SBE C++ Decoder

The service includes a high-performance C++ extension for parsing Binance SBE binary messages.

### Building the SBE Decoder

```bash
# Build the C++ extension
./build_sbe_decoder.sh

# Verify installation
python -c "from sbe_decoder_cpp import SBEDecoder; print('SBE decoder loaded!')"
```

### Performance Benefits

- **Sub-millisecond parsing**: C++ binary parsing vs Python JSON parsing
- **Memory efficient**: Direct binary access without string conversion
- **Type safety**: Compile-time validation of message structures
- **Schema validation**: Built-in SBE header and template validation

### Requirements

The SBE client requires:
- C++ compiler (for building the decoder extension)
- Binance API key (for SBE stream authentication)
- Python 3.8+ with pybind11 support

## Development

### Testing

```bash
# Run all tests
pytest

# Run unit tests only
pytest tests/unit/

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test
pytest tests/unit/test_kinesis_client.py::TestKinesisProducer::test_put_record
```

### Code Quality

```bash
# Format code
black src/ tests/

# Sort imports
isort src/ tests/

# Lint
flake8 src/ tests/

# Type checking
mypy src/
```

### Adding New Features

1. **Update Configuration**: Add new settings to `src/config/settings.py`
2. **Implement Feature**: Add code with proper error handling and logging
3. **Add Tests**: Unit tests for logic, integration tests for workflows
4. **Update Monitoring**: Add relevant metrics and health checks
5. **Document**: Update this README and add inline documentation

## Deployment

### AWS ECS

```bash
# Build and push to ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <account>.dkr.ecr.us-east-1.amazonaws.com
docker build -t bitcoin-ingestor .
docker tag bitcoin-ingestor:latest <account>.dkr.ecr.us-east-1.amazonaws.com/bitcoin-ingestor:latest
docker push <account>.dkr.ecr.us-east-1.amazonaws.com/bitcoin-ingestor:latest

# Deploy via ECS task definition
aws ecs update-service --cluster bitcoin-cluster --service ingestor-service --force-new-deployment
```

### Environment Variables

```bash
CONFIG_FILE=/app/config/prod.yaml
AWS_REGION=us-east-1
AWS_DEFAULT_REGION=us-east-1
```

## Troubleshooting

### Common Issues

1. **WebSocket Disconnections**
   - Check network connectivity
   - Verify Binance endpoint availability
   - Review reconnection logs

2. **Kinesis Throttling**
   - Increase shard count
   - Reduce batch size
   - Check circuit breaker status

3. **S3 Write Failures**
   - Verify IAM permissions
   - Check bucket policy
   - Review error logs

4. **High Memory Usage**
   - Check deduplication cache size
   - Review batch sizes
   - Monitor queue depths

### Logs Analysis

```bash
# View structured logs
docker logs bitcoin-ingestor | jq '.message'

# Filter by level
docker logs bitcoin-ingestor | jq 'select(.level=="ERROR")'

# Monitor health
watch -n 5 'curl -s http://localhost:8080/health | jq'
```

## Performance Tuning

### Throughput Optimization

- Increase `kinesis_batch_size` for higher throughput
- Reduce `kinesis_flush_interval_seconds` for lower latency
- Tune `rate_limit_requests_per_minute` based on API limits

### Memory Optimization

- Adjust deduplication window size
- Monitor queue sizes
- Use compression for S3 writes

### Latency Optimization

- Minimize batch sizes
- Reduce flush intervals
- Optimize network configuration

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Ensure all tests pass
5. Submit a pull request

## License

This project is licensed under the MIT License - see the LICENSE file for details.