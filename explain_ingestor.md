# Ingestor Service Explanation

## Overview

The Ingestor Service is the first component in the Bitcoin trading data pipeline, responsible for consuming real-time and historical market data from Binance and streaming it to AWS Kinesis Data Streams for downstream processing. It serves as the critical entry point that normalizes, serializes, and reliably delivers market data to the rest of the pipeline.

## Core Responsibilities

### 1. Data Ingestion
- **Real-time Data**: Connects to Binance WebSocket streams to receive live market data
- **Historical Data**: Fetches historical data via Binance REST API for backfilling
- **Multi-stream Support**: Handles multiple data types (trades, order book depth, candlestick data)

### 2. Data Processing
- **Normalization**: Converts Binance-specific data formats to internal schema
- **Serialization**: Uses Avro serialization for efficient, schema-aware data encoding
- **Validation**: Ensures data quality and schema compliance before transmission

### 3. Data Delivery
- **Kinesis Integration**: Streams processed data to AWS Kinesis Data Streams
- **Batching**: Optimizes throughput with configurable batch sizes and flush intervals
- **Reliability**: Implements retry logic and error handling for robust data delivery

## Architecture Components

### Core Modules

#### 1. WebSocket Client (`websocket_client.py`)
- Maintains persistent connection to `wss://stream.binance.com:9443/ws/`
- Subscribes to multiple streams:
  - **Trade streams**: Individual trade executions
  - **Depth streams**: Order book updates
  - **Kline streams**: Candlestick/OHLCV data
- Features:
  - Auto-reconnection with exponential backoff
  - Heartbeat monitoring (30-second intervals)
  - Graceful error handling and logging

#### 2. REST Client (`rest_client.py`)
- Interfaces with Binance REST API at `https://api.binance.com`
- Key endpoints:
  - `/api/v3/klines`: Historical candlestick data
  - `/api/v3/trades`: Historical trade data
  - `/api/v3/depth`: Order book snapshots
- Features:
  - Rate limiting compliance
  - Retry logic with exponential backoff
  - Pagination support for large data ranges

#### 3. Serializer (`serializer.py`)
- Loads Avro schema from `schemas/avro/market_data.avsc`
- Serializes market data to binary Avro format
- Schema validation and type conversion
- Supports schema evolution for forward/backward compatibility

#### 4. Kinesis Producer (`kinesis_producer.py`)
- AWS Kinesis Data Streams client using boto3
- Batched record publishing for optimal throughput
- Configurable buffering (default: 500 records or 1-second intervals)
- Partition key generation for even shard distribution
- Circuit breaker pattern for service resilience

#### 5. Health Check Service (`health_check.py`)
- HTTP endpoints for monitoring:
  - `GET /health`: Overall service health
  - `GET /ready`: Readiness probe for container orchestration
  - `GET /live`: Liveness probe
- Status checks:
  - WebSocket connection state
  - Kinesis producer health
  - Message processing rates
  - Memory usage

#### 6. Metrics Collection (`metrics.py`)
- Comprehensive metrics tracking:
  - `messages_received_total`: Counter by symbol and stream type
  - `message_processing_latency_seconds`: Processing latency histogram
  - `kinesis_batch_size`: Batch size distribution
  - `websocket_reconnection_count`: Connection stability
- Dual emission to Prometheus and CloudWatch

### Data Schema

The service uses a standardized Avro schema (`market_data.avsc`) with fields:
- `symbol`: Trading pair (e.g., "BTCUSDT")
- `timestamp`: Unix timestamp in milliseconds
- `price`: Trade execution price
- `volume`: Trade volume
- `bid_price`/`ask_price`: Optional order book data
- `source`: Data origin ("websocket" or "rest")
- `event_type`: Event classification ("trade", "depth", "kline")

## Data Flow

1. **Ingestion**: WebSocket client receives real-time data or REST client fetches historical data
2. **Transformation**: Raw Binance data is converted to internal MarketData schema
3. **Serialization**: Data is serialized to Avro binary format with schema validation
4. **Buffering**: Records are batched in memory for efficient transmission
5. **Delivery**: Batched records are sent to Kinesis Data Streams
6. **Monitoring**: Metrics are collected and health status is updated throughout

## Error Handling & Resilience

### WebSocket Resilience
- Automatic reconnection on connection loss
- Exponential backoff (1s → 2s → 4s → ... up to 60s)
- Graceful handling of Binance rate limits
- Heartbeat detection for connection health

### Kinesis Resilience
- Retry logic for throttling exceptions
- Circuit breaker pattern when Kinesis is unavailable
- Dead letter queue for failed records after max retries
- Batch failure handling with partial retry

### Service Resilience
- Graceful shutdown on SIGTERM/SIGINT
- Buffer flushing during shutdown
- Health degradation states vs. complete failure
- Comprehensive error logging with context

## Configuration

The service uses environment-specific YAML configuration files:
- `config/local.yaml`: Local development with LocalStack
- Configuration includes:
  - Binance endpoints and symbol lists
  - Kinesis stream names and batch settings
  - Health check ports and intervals
  - Retry policies and backoff parameters

## Monitoring & Observability

### Key Metrics
- **Latency**: End-to-end processing time from WebSocket to Kinesis
- **Throughput**: Messages per second by symbol and event type
- **Reliability**: Success/failure rates for each component
- **Resource Usage**: Memory, CPU, and network utilization

### Health Checks
- **WebSocket Health**: Connection status and last message timestamp
- **Kinesis Health**: Producer status and recent write success
- **Overall Health**: Composite status considering all components

### Alerting
- WebSocket disconnection → Trigger reconnection
- Kinesis write failures → Circuit breaker activation
- Processing latency spikes → Performance investigation
- Memory/CPU thresholds → Resource scaling

## Integration Points

### Upstream (Binance)
- WebSocket streams for real-time data
- REST API for historical backfill
- Rate limit compliance and error handling

### Downstream (Kinesis)
- Primary output: `bitcoin-market-data` stream
- Heartbeat output: `ingestor-heartbeat` stream
- Schema: Avro-serialized MarketData records

### Infrastructure
- Docker containerization for deployment
- AWS IAM roles for Kinesis access
- LocalStack for local development
- Prometheus/CloudWatch for monitoring

## Critical Requirements

- **Low Latency**: Minimize processing delay to maintain real-time characteristics
- **High Reliability**: Must handle network issues and service disruptions gracefully
- **Data Quality**: Ensure schema compliance and prevent corrupted data downstream
- **Observability**: Comprehensive monitoring for operational visibility
- **Scalability**: Support multiple symbols and high-frequency data streams

The Ingestor Service forms the foundation of the trading pipeline, ensuring reliable, low-latency delivery of market data that enables accurate real-time analysis and trading decisions downstream.