# Data Collected, Sources, and ML Usage

This document explains exactly what market data the ingestor collects from Binance, how each record is shaped, and how the data is used for model training (offline) and inference (online).

- Runtime entry: `services/ingestor/src/main.py`
- REST client: `services/ingestor/src/clients/binance_rest.py`
- WebSocket client (JSON now, SBE-ready): `services/ingestor/src/clients/binance_sbe.py`
- S3 writer (bronze): `services/ingestor/src/data/s3_writer.py`
- Kinesis producer: `services/ingestor/src/clients/kinesis_client.py`
- Environment configs: `services/ingestor/config/{local,dev,prod}.yaml`

## Data Sources
- REST (historical/backfill to S3)
  - `aggTrades` (aggregated trades)
  - `trades` (individual trades)
  - `klines` (candlesticks)
  - `depth` snapshot (top-N order book snapshot)
- WebSocket (real-time to Kinesis)
  - `trade` (executed trades stream)
  - `bookTicker` (best bid/ask updates)
  - `depth@100ms` (incremental order book deltas)

Note: The “SBE” client currently normalizes JSON WebSocket messages; SBE binary decoding can be added later.

## Record Types and Fields
All timestamps are epoch milliseconds. Prices and sizes are numeric floats unless stated otherwise.

### 1) MarketTrade
- Source
  - REST: `aggTrades` backfill (source = `"rest"`)
  - WS: `trade` stream (source = `"sbe"` — naming kept for future SBE)
- Fields
  - `symbol` (string)
  - `event_ts` (int): trade event time (Binance `E`/`T`)
  - `ingest_ts` (int): time when we ingested the message
  - `trade_id` (int): REST uses `aggTradeId` (`a`), WS uses `t`
  - `price` (float)
  - `qty` (float)
  - `is_buyer_maker` (bool): Binance `m`
  - `source` (string): `rest` or `sbe`
- Example (WS)
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
- Typical features/labels
  - Returns, volatility, signed volume, trade imbalance, short-horizon midprice move labels.

### 2) BestBidAsk (Top of Book)
- Source: WS `bookTicker` (source = `"sbe"`)
- Fields
  - `symbol` (string)
  - `event_ts` (int)
  - `ingest_ts` (int)
  - `bid_px` (float), `bid_sz` (float)
  - `ask_px` (float), `ask_sz` (float)
  - `source` (string)
- Example
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
- Typical features
  - Spread, microprice, quote imbalance (OBI), top-of-book dynamics.

### 3) DepthDelta (Incremental Order Book)
- Source: WS `depthUpdate` (source = `"sbe"`)
- Fields
  - `symbol` (string)
  - `event_ts` (int)
  - `ingest_ts` (int)
  - `bids` (list of [price, size] as strings)
  - `asks` (list of [price, size] as strings)
  - `source` (string)
- Example
  ```json
  {
    "symbol": "BTCUSDT",
    "event_ts": 1640995200000,
    "ingest_ts": 1640995200100,
    "bids": [["44999.99","0.5"],["44999.98","1.0"]],
    "asks": [["45000.01","0.3"],["45000.02","0.8"]],
    "source": "sbe"
  }
  ```
- Typical features
  - Multi-level book imbalance, liquidity/pressure, order flow, depth-weighted prices.

### 4) Klines (Candles)
- Source: REST `klines` (backfill)
- Fields (normalized before writing to S3)
  - `open_time`, `close_time` (int)
  - `open_price`, `high_price`, `low_price`, `close_price` (float)
  - `volume`, `quote_volume` (float)
  - `trade_count` (int)
  - `taker_buy_base_volume`, `taker_buy_quote_volume` (float)
  - `symbol` (string), `interval` (string), `ingest_ts` (int)
- Typical uses
  - Coarser features, context windows, sanity checks when training.

### 5) Depth Snapshot (Historical)
- Source: REST `depth` (snapshot)
- Fields (written as a one-record JSONL file)
  - `symbol` (string)
  - `timestamp` (int): snapshot time
  - `ingest_ts` (int)
  - `last_update_id` (int)
  - `bids`, `asks` (arrays of [px, sz])
  - `source` = `"rest"`
- Typical uses
  - Seed/validate book state for backtests and feature reconstruction.

## Where Data Goes
- Real-time (WS → Kinesis Data Streams)
  - Trade → `aws.kinesis_trade_stream`
  - BestBidAsk → `aws.kinesis_bba_stream`
  - DepthDelta → `aws.kinesis_depth_stream`
  - See `services/ingestor/config/*.yaml` for stream names per environment.
- Historical (REST → S3 Bronze)
  - JSONL (gz) with time partitioning: `bronze/{symbol}/{data_type}/yyyy=YYYY/mm=MM/dd=DD/hh=HH/file.jsonl.gz`
  - See `s3_bucket` and `s3_bronze_prefix` in config.

## Training vs Inference
- Training (offline, batch)
  - Use REST backfilled data in S3 to build datasets.
  - Engineer features from trades, BBA, depth, and klines over rolling windows.
  - Create labels (e.g., future midprice move over N seconds). Train and validate models.
- Inference (online, streaming)
  - Consume WS-derived Kinesis streams to compute the same features in real time.
  - Feed feature vectors to an inference service (not in this package) to emit predictions.
  - Monitor via `/health` and metrics; autoscale or alert as needed.

## Important Semantics
- `event_ts` vs `ingest_ts`
  - `event_ts`: when the market event occurred (exchange time).
  - `ingest_ts`: when we processed/received it (pipeline time).
- IDs
  - `trade_id`: REST aggTrades uses `a` (aggTradeId); WS uses `t`.
- Types
  - Depth arrays are strings from Binance; downstream systems should cast to float.
- Deduplication
  - S3 writes perform in-process deduplication by record keys; Kinesis producer handles retries and circuit breaking.

## Configuration Quick Links
- Local dev (LocalStack): `services/ingestor/config/local.yaml`
- Development: `services/ingestor/config/dev.yaml`
- Production: `services/ingestor/config/prod.yaml`

This layout aligns the same core schemas across REST (historical) and WS/SBE (real-time), ensuring features built offline can be reproduced online for consistent training and inference.

