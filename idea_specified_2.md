Here’s a **single Markdown plan** (regression-only) with a clear **DB + data movement pipeline** from REST backfill → training → SBE-only live inference. It fits your repo layout and keeps the **train == infer** feature contract tight.

---

```markdown
# Bitcoin Data Pipeline — Regression-Only Plan (REST training, SBE inference)

**Objective:**  
Predict **10-second ahead log-return** for `BTCUSDT` with a **lightweight MLP (regression)**.  
- **Training (offline):** REST market data (aggTrades / trades / klines; optional depth snapshots).  
- **Inference (live):** **SBE WebSocket only** (`trade`, `bestBidAsk`, `depth`).  
- **Cadence:** Emit a prediction **every 1–2 seconds**.  
- **Deadline:** end-to-end tick (features + inference) **≤ 100 ms** (soft real-time; skip late ticks).

---

## 📂 Project Structure

```

Bitcoin_datapipeline/
├── services/
│   ├── ingestor/            # REST backfill + SBE live publisher → Kinesis/Kafka
│   │   ├── src/
│   │   ├── config/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── flink-processor/     # Stream features: VWAP/TVI/volatility (writes Redis + S3 Silver)
│   │   ├── src/
│   │   ├── config/
│   │   └── Dockerfile
│   ├── inference/           # ONNX MLP regression service (pulls features from Redis)
│   │   ├── src/
│   │   ├── models/
│   │   ├── config/
│   │   └── Dockerfile
│   └── feature-store/       # (Optional) Feast project wrapper around Redis (online) + S3 (offline)
├── schemas/
│   ├── avro/
│   └── proto/
├── infrastructure/
│   ├── terraform/           # AWS: Kinesis Data Streams, ElastiCache Redis, S3, ECS/EKS, IAM
│   ├── docker-compose.yml   # Local dev: LocalStack (S3/Kinesis), Redis, Flink, MinIO
│   └── k8s/                 # Deploy manifests/Helm
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
└── docs/

````

---

## 🧠 Modeling (Regression-Only)

**Target (label):**  
\[
y_t = r_{t\rightarrow t+10\text{s}} = \log(\text{mid}_{t+10\text{s}}) - \log(\text{mid}_t)
\]
where \( \text{mid}_t = \frac{\text{bestBid}_t + \text{bestAsk}_t}{2} \).  
If mid isn’t available in training, use a consistent **proxy** (e.g., last trade price or VWAP) and keep the same definition at inference.

**Model:** Light MLP regressor  
- Input: 20–40 engineered features (list below).  
- Body: `in → 64 → 32 → 1` (ReLU, Dropout 0.1).  
- Loss: **Huber** (robust to tails).  
- Export: **ONNX** for CPU inference (fast).  
- Metrics: **MAE**, **MSE**, and **Directional hit-rate** (sign correctness).

---

## 🔑 Train == Infer Feature Contract

### Minimal Trade-First Feature Set (Schema v1)
_All computable from REST trades/aggTrades for training & from SBE raw trades for live. One OB field `spread` requires bestBidAsk live (SBE)._

- **Returns:** `ret_1s`, `ret_2s`, `ret_5s` (log-returns using last price or VWAP)  
- **VWAP deviation:** `vwap_5s_dev`  
- **Activity:** `n_trades_1s`, `n_trades_5s`  
- **Trade flow imbalance:** `buy_vol_1s`, `sell_vol_1s`, `tvi_1s`; `buy_vol_5s`, `sell_vol_5s`, `tvi_5s`  
- **Microstructure:** `avg_trade_size_1s`, `vol_ret_10s` (std of 1s returns over 10s)  
- **Regime flags:** `burst_1s` (n_trades_1s > rolling 60s median), `large_trade_flag_5s` (≥95th pct)  
- **Recency:** `time_since_last_trade_ms`  
- **Deltas:** `last_price_minus_1s`, `last_price_minus_5s`  
- **(Optional) OB:** `spread = ask1 - bid1` _(from SBE bestBidAsk at inference; for training either approximate or exclude until OB history is recorded)_

> Persist **`schema_v1.json`** (ordered list + units) and **`scaler.pkl`** from training. Use them byte-for-byte at inference.

---

## 🏗️ Data Architecture & Movement

### Storage Layers
- **Data Lake (S3)**  
  - **Bronze/raw:** REST backfills (JSONL/Parquet) + optional SBE raw append (if you persist live).  
  - **Silver/curated:** Resampled 1s feature tables with exact windows & label alignment.  
  - **Gold/serving:** Model-ready training sets + predictions archive.

- **Message Bus**: **Amazon Kinesis Data Streams**  
  - Streams: `market-sbe-trade`, `market-sbe-bestbidask`, `market-sbe-depth`, `features-1s`, `predictions-1s`.
  - **Kinesis Data Firehose** for S3 delivery from streams.

- **Online Feature Store**: **Amazon ElastiCache (Redis)**  
  - Keys: `features:{symbol}:{ts_sec}`  
  - TTL: 120–300s (keeps a rolling cache)  
  - Value: JSON (or Protobuf) of schema_v1 features.

- **Stream Processing**: **Amazon Kinesis Data Analytics (Apache Flink)**  
  - Managed Flink applications for real-time feature computation.

- **Model Registry**: **Amazon SageMaker Model Registry** or S3 versioning of `model.onnx` + `scaler.pkl` + `schema_v1.json`.

- **Metrics/Logs**: **Amazon CloudWatch** (metrics, logs), **AWS X-Ray** (tracing), S3 (prediction archival).

---

## 🔄 End-to-End Flow

### 1) **REST Backfill → S3 (Bronze)**
- **services/ingestor (REST mode)** pulls:
  - `aggTrades` (+ `trades` sanity), optionally `klines` & `/depth` snapshot.
- Writes **raw JSONL** to `s3://bitcoin-data-lake/bronze/{symbol}/aggTrades/yyyy=.../mm=.../dd=.../hh=.../*.jsonl`.

**TODO**
- [ ] Pagination by `startTime`/`endTime`, resumable by last timestamp.  
- [ ] Exponential backoff + HTTP 429 handling.  
- [ ] Idempotent appends; dedup by `(symbol, aggTradeId)` or `(symbol, tradeId, ts)`.

### 2) **Feature Build (Training) → S3 (Silver/Gold)**
- **features/build_train_features.py** reads Bronze trades → resamples to **1s grid**, builds **Schema v1** features, then computes **label** \(y_t\) using strict \(t \to t+10s\) timestamps.
- Output:
  - **Silver:** `s3://bitcoin-data-lake/silver/{symbol}/features_1s/*.parquet` (features only)  
  - **Gold:**   `s3://bitcoin-data-lake/gold/{symbol}/train_1s/*.parquet` (features + label)

**TODO**
- [ ] O(1) rolling windows (deque/ring buffers) for speed.  
- [ ] Use **exchange event time** (not local clock).  
- [ ] Verify no leakage (drop last 10s tail).

### 3) **Train MLP (Regression) → Model Registry**
- **modeling/train.py**:
  - Time-split (train/val/test by contiguous blocks).
  - Fit **StandardScaler/RobustScaler** on train only.
  - Train Light MLP regression (Huber loss).
  - Save `{model.onnx, scaler.pkl, schema_v1.json}` to **SageMaker Model Registry** or S3.
  - Record metrics in **Amazon SageMaker Experiments**.

**TODO**
- [ ] Directional hit-rate and MAE dashboards.  
- [ ] Export test-time evaluation plots.

### 4) **SBE Live Ingest → Bus → Stream Features → Redis**
- **services/ingestor (SBE mode)**:
  - Connect to **SBE** (`trade`, `bestBidAsk`, `depth`), **decode**, normalize to internal events.
  - Publish to **Kinesis Data Streams**: `market-sbe-trade`, `market-sbe-bestbidask`, `market-sbe-depth`.
  - (Optional) Also append raw SBE to S3 **Bronze** via **Kinesis Data Firehose** for replay.

- **Kinesis Data Analytics (Flink)**:
  - Consumes SBE streams, maintains rolling state, computes **Schema v1** features **each second**.
  - Writes:
    - **ElastiCache Redis** key `features:{symbol}:{ts_sec}` (TTL 120–300s).
    - **S3 Silver append** (`features_1s_live/*.parquet`) via **Kinesis Data Firehose** for audit/backfill convergence.

**TODO**
- [ ] Local order book maintenance (seed `/depth` snapshot; apply SBE `depth` deltas).  
- [ ] Handle out-of-order, duplicate, or auto-culled events.  
- [ ] Exactly-once semantics (idempotent writes) where possible.

### 5) **Inference Service (ONNX) → Predictions Stream + Archive**
- **services/inference (ECS/EKS)**:
  - Loads `{model.onnx, scaler.pkl, schema_v1.json}` from **SageMaker Model Registry** or S3.
  - Tick **every 1–2s**:
    - Pull from **ElastiCache Redis** the latest features for `{symbol, now_sec}`.  
    - If stale: optional **fallback compute** from the last few seconds of Kinesis messages.  
    - **Scale → ONNX predict** → \( \hat{y}_t \) (10s log-return).
    - Emit to **Kinesis Data Streams** `predictions-1s` and archive to `s3://bitcoin-data-lake/gold/predictions_1s/*.parquet` via **Kinesis Data Firehose**.
  - **Deadline guard:** if tick > 100 ms, **skip** and move on.
  - **Monitoring:** CloudWatch metrics for latency, error rates, prediction distribution.

**TODO**
- [ ] Confidence/uncertainty proxy: e.g., rolling residual std from validation.  
- [ ] Optional decisioning (thresholds) handled in a separate strategy module.

---

## 🧾 Schemas (Avro examples)

### `MarketTrade.avsc`
```json
{
  "type": "record",
  "name": "MarketTrade",
  "namespace": "binance",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "event_ts", "type": "long"},      // exchange event time (ms)
    {"name": "ingest_ts", "type": "long"},     // local receive time (ms)
    {"name": "trade_id", "type": "long"},
    {"name": "price", "type": "double"},
    {"name": "qty", "type": "double"},
    {"name": "is_buyer_maker", "type": "boolean"},
    {"name": "source", "type": "string"}       // "sbe" | "rest"
  ]
}
````

### `BestBidAsk.avsc`

```json
{
  "type": "record",
  "name": "BestBidAsk",
  "namespace": "binance",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "event_ts", "type": "long"},
    {"name": "ingest_ts", "type": "long"},
    {"name": "bid_px", "type": "double"},
    {"name": "bid_sz", "type": "double"},
    {"name": "ask_px", "type": "double"},
    {"name": "ask_sz", "type": "double"},
    {"name": "source", "type": "string"}
  ]
}
```

### `DepthDelta.avsc` (top-N compressed)

```json
{
  "type": "record",
  "name": "DepthDelta",
  "namespace": "binance",
  "fields": [
    {"name": "symbol", "type": "string"},
    {"name": "event_ts", "type": "long"},
    {"name": "ingest_ts", "type": "long"},
    {"name": "bids", "type": {"type": "array", "items": {"type":"array","items":"string"}}}, // [[px,qty],...]
    {"name": "asks", "type": {"type": "array", "items": {"type":"array","items":"string"}}},
    {"name": "source", "type": "string"}
  ]
}
```

### `FeatureVector1s.avsc` (Schema v1)

```json
{
  "type": "record",
  "name": "FeatureVector1s",
  "namespace": "features",
  "fields": [
    {"name":"symbol","type":"string"},
    {"name":"ts_sec","type":"long"},
    {"name":"ret_1s","type":"double"},
    {"name":"ret_2s","type":"double"},
    {"name":"ret_5s","type":"double"},
    {"name":"vwap_5s_dev","type":"double"},
    {"name":"n_trades_1s","type":"int"},
    {"name":"n_trades_5s","type":"int"},
    {"name":"buy_vol_1s","type":"double"},
    {"name":"sell_vol_1s","type":"double"},
    {"name":"tvi_1s","type":"double"},
    {"name":"buy_vol_5s","type":"double"},
    {"name":"sell_vol_5s","type":"double"},
    {"name":"tvi_5s","type":"double"},
    {"name":"avg_trade_size_1s","type":"double"},
    {"name":"vol_ret_10s","type":"double"},
    {"name":"burst_1s","type":"int"},
    {"name":"large_trade_flag_5s","type":"int"},
    {"name":"time_since_last_trade_ms","type":"int"},
    {"name":"last_price_minus_1s","type":"double"},
    {"name":"last_price_minus_5s","type":"double"},
    {"name":"spread","type":["null","double"],"default":null}
  ]
}
```

### `Prediction1s.avsc`

```json
{
  "type": "record",
  "name": "Prediction1s",
  "namespace": "predictions",
  "fields": [
    {"name":"symbol","type":"string"},
    {"name":"ts_sec","type":"long"},
    {"name":"yhat_log_return_10s","type":"double"},
    {"name":"latency_ms","type":"double"},
    {"name":"model_version","type":"string"}
  ]
}
```

---

## 🛠️ Service Responsibilities (TODO Checklists)

### services/ingestor

* [ ] **REST mode:** backfill aggTrades/trades/klines → S3 Bronze (resumable, dedupe).
* [ ] **SBE mode:** connect, **decode**, normalize → publish to `market.sbe.*` streams.
* [ ] Health endpoint + metrics (msg rate, decode errors, reconnect count).

### services/flink-processor

* [ ] Consume `market.sbe.*`; maintain rolling windows; compute **Schema v1** features **per second**.
* [ ] Write **Redis** (TTL 120–300s) and append to **S3 Silver**.
* [ ] Optional local order book module (snapshot + diffs, handle gaps/culling).

### services/inference

* [ ] Load `model.onnx`, `scaler.pkl`, `schema_v1.json`.
* [ ] **Every 1–2s**: fetch features from Redis by `{symbol, ts_sec}`; if missing/stale, fallback to local compute with last N seconds from bus.
* [ ] Scale → ONNX infer → emit to `predictions.1s` + S3 Gold.
* [ ] Enforce **deadline**; log latency; skip tardy ticks.

### feature-store (optional Feast)

* [ ] Define entity `symbol` + `ts_sec`.
* [ ] Online store Redis; offline store S3.
* [ ] Registry in S3; materialize features to online.

---

## ⚙️ Config Examples

### `services/ingestor/config/config.yaml`

```yaml
symbols: ["BTCUSDT"]
rest:
  base_url: "https://data-api.binance.vision"
sbe:
  ws_url: "wss://stream.binance.com:9443"   # ensure SBE subprotocol if required
aws:
  region: "us-east-1"
  kinesis:
    streams:
      trade: "market-sbe-trade"
      bba:   "market-sbe-bestbidask"
      depth: "market-sbe-depth"
  s3:
    bucket: "bitcoin-data-lake"
    prefix: "bronze"
```

### `services/inference/config/config.yaml`

```yaml
symbol: "BTCUSDT"
cadence_ms: 1000
deadline_ms: 100
aws:
  region: "us-east-1"
  elasticache:
    cluster_endpoint: "bitcoin-features.cache.amazonaws.com:6379"
  sagemaker:
    model_registry_name: "bitcoin-trading-model"
  kinesis:
    predictions_stream: "predictions-1s"
  s3:
    bucket: "bitcoin-data-lake"
    prefix: "gold/predictions_1s"
model:
  local_cache_dir: "/tmp/models"
```

---

## 🧪 Testing Strategy

**Unit**

* Feature computations (rolling VWAP/TVI/vol).
* Label calculation (t → t+10s).
* MLP forward, scaler consistency.

**Integration**

* REST backfill → S3 Bronze; deterministic slices.
* SBE ingest → Kinesis → Kinesis Data Analytics (Flink) → ElastiCache/S3 Silver.
* Inference end-to-end with **LocalStack** (S3/Kinesis), **Redis**, **Flink** for local dev.
* AWS integration tests with **Kinesis Data Streams**, **ElastiCache**, **SageMaker**.

**E2E / Performance**

* Replay day of data; validate that online feature vectors ≈ offline built (tolerance).
* Latency histograms (p50/p90/p99) < deadline.
* Backpressure handling (bus rate spikes).

---

## 📈 Monitoring & Alerts

* **Technical**: ingest throughput, decode errors, feature freshness (`now_sec - ts_sec`), inference latency p95/p99, ElastiCache hit-rate.
* **Model**: rolling MAE, directional hit-rate, residual std; drift on feature means/std.
* **AWS Services**: Kinesis shard utilization, ECS/EKS resource metrics, SageMaker endpoint health.

**Alerts (CloudWatch)**

* Feature staleness (`feature_age > 3s`) → **SNS → Slack**
* Inference latency (`p95 > 100ms`) → **SNS → PagerDuty**
* ElastiCache miss-rate (`> 5%`) → **SNS → Slack**
* Kinesis consumer lag (`> threshold`) → **CloudWatch Alarm → SNS**

---

## 🧭 MVP Order (Regression)

1. **REST backfill → S3 Bronze** (aggTrades)
2. **Offline features + labels → S3 Gold**; train MLP; export ONNX + scaler + schema
3. **SBE ingest → bus** and **Flink features → Redis** (per-second)
4. **Inference service** every 1–2s from Redis → predictions stream + S3 archive
5. **Monitoring** dashboards + basic alerts

---

## ✅ Acceptance

* REST Bronze complete without gaps/dupes; Silver/Gold aligned to 1s grid.
* `schema_v1.json` & `scaler.pkl` fixed and used identically live.
* Inference p99 latency ≤ deadline; drop rate (missed ticks) low.
* Shadow evaluation (no trading) shows stable MAE and directional hit-rate across regimes.

```

--- 

If you want, I can turn **any box** above into code next (e.g., `features/build_train_features.py` scaffolding + `modeling/train.py` with Huber loss and ONNX export, or the **Flink window definitions** for the per-second feature stream).
```
