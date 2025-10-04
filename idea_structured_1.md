'''
[Binance]
 ├─ WebSocket (real-time stream)
 └─ REST API (historical + backfill)

      │
      ▼
[Ingestor Service]
 ├─ Normalizes to Avro/Proto
 ├─ Emits heartbeat
 └─ Writes → Kinesis Data Streams (KDS)

      │
      ├─────────► [Kinesis Firehose] → [S3 Raw / Iceberg Tables]
      │
      └─────────► [Flink / Kinesis Data Analytics]
                  ├─ Compute rolling features (VWAP, vol, imbalance)
                  ├─ Write to Redis (TTL, last-known-good snapshot)
                  └─ Emit staleness metrics

      │
      ▼
[Inference Service (ECS/EKS, always warm)]
 ├─ Consumes from KDS
 ├─ Fetch features from Redis
 ├─ Fallback Controller:
 │    1. Use fresh online features if within budget
 │    2. Repair slightly stale with deltas
 │    3. Impute via EMA/Kalman carry-forward
 │    4. Pull microbatch features from S3/Iceberg
 │    5. Otherwise → Safe mode (No-Trade)
 ├─ Model (ONNX/TensorRT/XGBoost)
 └─ Inline Risk Engine (limits, circuit breakers)

      │
      ├─ YES → [Exchange Adapter → Trade Execution]
      └─ NO  → [Discard / No-Trade]

      │
      ▼
[Predictions Stream (Kinesis)]
 └─ Firehose → S3 Predictions / Audit Log

      │
      ▼
[Offline ETL & Feature Store]
 ├─ Glue jobs → build point-in-time Iceberg views
 ├─ Feast Feature Store
 │    • Offline = Iceberg on S3
 │    • Online = Redis / DynamoDB
 └─ Provides consistent features for training & serving

      │
      ▼
[Training Jobs]
 ├─ Incremental (every few min): update head / small learner
 └─ Periodic full retrain (6–24h): rebuild base model
      • Outputs to Model Registry (SageMaker/MLflow)

      │
      ▼
[Model Registry]
 ├─ Stores model artifacts + feature versions
 └─ Safe deployment: shadow → canary → full rollout

      │
      ▼
[Orchestration & Monitoring]
 ├─ Airflow (MWAA): batch DAGs (ETL, retrain, quality checks)
 ├─ EventBridge: triggers incremental updates
 ├─ Step Functions: model deploy workflow
 ├─ CloudWatch / Prometheus: infra + latency metrics
 ├─ Great Expectations / Deequ: data quality
 └─ Alerts → Slack/SNS

'''