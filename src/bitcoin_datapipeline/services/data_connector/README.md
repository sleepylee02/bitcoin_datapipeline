# Data Connector Service

## Service Overview
**Purpose:** S3 data lake ETL processing and RDBMS integration for MLOps training pipeline  
**Deployment:** Single Docker container / AWS ECS service  
**Ports:** 8083 (health endpoint)  
**MLOps Role:** Feature store, experiment tracking, structured training data

## Architecture Role
```
┌─────────────────────────────────────────────────────────────────┐
│                   DATA CONNECTOR SERVICE (MLOps Hub)           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  S3 Bronze ──► ETL Pipeline ──► RDBMS ──► ML Training Pipeline │
│  (raw data) │  (transform)    │ (features) │  (models)          │
│             │                 │           │                    │
│             ▼                 ▼           ▼                    │
│       ┌──────────────┐  ┌──────────────┐ ┌──────────────┐      │
│       │S3 Reader     │  │Feature       │ │Experiment    │      │
│       │(bronze/silver│  │Engineering   │ │Tracking      │      │
│       │ scanner)     │  │(SQL transforms)│ │(MLflow style)│      │
│       └──────────────┘  └──────────────┘ └──────────────┘      │
│             ▼                 ▼           ▼                    │
│       ┌──────────────┐  ┌──────────────┐ ┌──────────────┐      │
│       │Data Quality  │  │Feature Store │ │Model Registry│      │
│       │Validation    │  │(time-series) │ │(versions)    │      │
│       └──────────────┘  └──────────────┘ └──────────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

## Core Responsibilities

### 1. MLOps Feature Store Pipeline
- **Bronze → Silver**: Normalize raw SBE/REST data into standardized formats
- **Silver → RDBMS**: Load structured data for fast ML training queries
- **Feature Engineering**: SQL-based feature computation and aggregation
- **Data Quality**: Validation, anomaly detection, and completeness checks

### 2. RDBMS Training Hub
- **Aurora PostgreSQL**: Optimized for ML training data access
- **Feature Store Tables**: Time-series data with fast temporal queries
- **Experiment Tracking**: Model versions, hyperparameters, results
- **Real-time Serving**: Sub-10ms feature lookups for inference

### 3. MLOps Integration
- **Model Registry**: Track trained models and their S3 artifacts
- **Experiment Management**: A/B testing, model comparison, metrics
- **Training Pipeline**: Automated retraining triggers based on data drift
- **Monitoring**: Feature drift detection, model performance tracking

## Docker Deployment

### Container Specifications
```yaml
# Docker container model
Service: data-connector
Base Image: python:3.12-slim
Resources:
  CPU: 2.0 vCPU (for data processing)
  Memory: 4GB (large dataset handling)
  Storage: 20GB (temporary processing space)
Ports:
  - 8083: Health/metrics endpoint
Environment:
  - CONFIG_FILE: config/prod.yaml
  - AWS_REGION: us-east-1
  - DB_HOST: ${RDS_ENDPOINT}
  - DB_PASSWORD: ${DB_PASSWORD}
```

### Build & Deploy
```bash
# Build container
docker build -t bitcoin-data-connector .

# Run locally
docker run -d --name data-connector \
  -p 8083:8083 \
  -e CONFIG_FILE=config/local.yaml \
  -e AWS_REGION=us-east-1 \
  -e DB_HOST=localhost \
  bitcoin-data-connector

# AWS ECS deployment
aws ecs update-service \
  --cluster bitcoin-cluster \
  --service data-connector \
  --task-definition data-connector:latest
```

## Configuration

### Local Development (`config/local.yaml`)
```yaml
aws:
  region: "us-east-1"
  s3_bucket: "bitcoin-data-lake"
  endpoint_url: "http://localhost:4566"  # LocalStack

database:
  host: "localhost"
  port: 5432
  database: "bitcoin_db"
  username: "postgres"
  password: "postgres"
  pool_size: 10
  
etl:
  batch_size: 10000
  processing_interval: "1h"
  silver_layer_retention_days: 90
  gold_layer_retention_days: 365

orchestration:
  scheduler_enabled: true
  max_concurrent_jobs: 3
  job_timeout_minutes: 60
```

### Production (`config/prod.yaml`)
```yaml
aws:
  region: "us-east-1"
  s3_bucket: "bitcoin-data-lake-prod"

database:
  host: "${DB_HOST}"
  port: 5432
  database: "bitcoin_prod"
  username: "bitcoin_user"
  password: "${DB_PASSWORD}"
  pool_size: 20
  ssl_mode: "require"

etl:
  batch_size: 50000  # Larger batches in prod
  processing_interval: "30m"
  enable_parallel_processing: true
  worker_count: 4
```

## ETL Pipeline Architecture

### 1. Bronze → Silver Transformation
```python
# Normalize raw data formats
BRONZE_TO_SILVER_JOBS = {
    "sbe_trades": {
        "source_pattern": "bronze/sbe/BTCUSDT/trade/*/*.parquet",
        "destination": "silver/normalized_trades/BTCUSDT/",
        "schema": "normalized_trade_schema_v2.json",
        "transformations": [
            "standardize_timestamps",
            "validate_price_precision", 
            "add_derived_fields",
            "deduplicate_records"
        ]
    },
    "rest_klines": {
        "source_pattern": "bronze/rest/BTCUSDT/klines/*/*.parquet",
        "destination": "silver/klines_1m/BTCUSDT/",
        "transformations": [
            "convert_to_time_series",
            "calculate_technical_indicators",
            "validate_ohlc_consistency"
        ]
    }
}
```

### 2. Silver → Gold Aggregation
```python
# Create analysis-ready datasets
SILVER_TO_GOLD_JOBS = {
    "feature_vectors": {
        "sources": [
            "silver/normalized_trades/BTCUSDT/",
            "silver/order_book_snapshots/BTCUSDT/",
            "silver/klines_1m/BTCUSDT/"
        ],
        "destination": "gold/feature_vectors_2s/BTCUSDT/",
        "aggregation_window": "2s",
        "features": [
            "price_returns",
            "volume_metrics", 
            "order_book_imbalance",
            "technical_indicators"
        ]
    },
    "prediction_labels": {
        "source": "silver/normalized_trades/BTCUSDT/",
        "destination": "gold/labels_10s/BTCUSDT/", 
        "label_calculation": "price_change_10s_ahead"
    }
}
```

### 3. MLOps Database Schema
```sql
-- Feature Store (optimized for ML training)
CREATE TABLE feature_store (
    timestamp TIMESTAMPTZ NOT NULL,
    symbol VARCHAR(10) NOT NULL,
    
    -- Price features
    price DECIMAL(20,8) NOT NULL,
    return_1s DECIMAL(10,6),
    return_5s DECIMAL(10,6),
    return_10s DECIMAL(10,6),
    
    -- Volume features  
    volume_1s DECIMAL(20,8),
    volume_5s DECIMAL(20,8),
    vol_imbalance_1s DECIMAL(6,4),
    vol_imbalance_5s DECIMAL(6,4),
    
    -- Order book features
    spread_bp DECIMAL(6,2),
    ob_imbalance DECIMAL(6,4),
    bid_strength DECIMAL(20,8),
    ask_strength DECIMAL(20,8),
    
    -- Technical indicators
    vwap_dev_1s DECIMAL(8,4),
    momentum DECIMAL(8,4),
    volatility DECIMAL(8,4),
    
    -- Labels (target variables)
    target_price_10s DECIMAL(20,8),  -- Price 10 seconds ahead
    target_return_10s DECIMAL(10,6), -- Return 10 seconds ahead
    
    -- Metadata
    data_quality_score DECIMAL(3,2),
    feature_completeness DECIMAL(3,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    
    PRIMARY KEY (timestamp, symbol)
);

-- Time-series index for fast training queries
CREATE INDEX idx_feature_store_time ON feature_store USING BRIN (timestamp);

-- ML Experiment Tracking
CREATE TABLE ml_experiments (
    experiment_id SERIAL PRIMARY KEY,
    experiment_name VARCHAR(100),
    model_type VARCHAR(50),
    model_version VARCHAR(20),
    
    -- Training configuration
    feature_set TEXT[],
    hyperparameters JSONB,
    training_start TIMESTAMPTZ,
    training_end TIMESTAMPTZ,
    
    -- Performance metrics
    validation_accuracy DECIMAL(6,4),
    test_accuracy DECIMAL(6,4),
    directional_accuracy DECIMAL(6,4),
    sharpe_ratio DECIMAL(6,4),
    
    -- Model artifacts
    s3_model_path TEXT,
    s3_feature_transformer_path TEXT,
    
    -- Status
    status VARCHAR(20) DEFAULT 'training',
    deployed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Model Registry
CREATE TABLE model_registry (
    model_id SERIAL PRIMARY KEY,
    model_name VARCHAR(100),
    version VARCHAR(20),
    experiment_id INTEGER REFERENCES ml_experiments(experiment_id),
    
    -- Deployment info
    deployed_at TIMESTAMPTZ,
    deployment_status VARCHAR(20),
    performance_metrics JSONB,
    
    -- Model metadata
    feature_schema JSONB,
    prediction_schema JSONB,
    s3_artifact_path TEXT,
    
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Feature Engineering Views
CREATE VIEW ml_training_data AS
SELECT 
    timestamp,
    price,
    return_1s,
    return_5s,
    volume_1s,
    vol_imbalance_1s,
    spread_bp,
    ob_imbalance,
    momentum,
    volatility,
    target_return_10s,
    data_quality_score
FROM feature_store 
WHERE data_quality_score > 0.95
  AND feature_completeness > 0.98;
```

## Data Quality Framework

### Validation Rules
```python
DATA_QUALITY_CHECKS = {
    "trades": {
        "schema_validation": {
            "required_fields": ["timestamp", "price", "quantity", "symbol"],
            "data_types": {"price": "float", "quantity": "float"},
            "constraints": {"price": "> 0", "quantity": "> 0"}
        },
        "business_rules": {
            "price_range": {"min": 1000, "max": 200000},  # USD bounds
            "timestamp_freshness": "< 1 hour old",
            "duplicate_detection": "composite_key: [timestamp, price, quantity]"
        }
    },
    "feature_vectors": {
        "completeness_threshold": 0.95,
        "feature_range_checks": {
            "returns": {"min": -0.1, "max": 0.1},  # 10% max return
            "volume": {"min": 0}
        },
        "correlation_checks": ["price_volume_correlation"]
    }
}
```

### Quality Metrics
```python
async def calculate_quality_metrics(dataset: str, timeframe: str) -> dict:
    """Calculate data quality metrics for monitoring"""
    return {
        "completeness": calculate_completeness_ratio(),
        "accuracy": validate_against_external_source(),
        "consistency": check_cross_dataset_consistency(),
        "timeliness": measure_data_freshness(),
        "uniqueness": detect_duplicate_rate(),
        "validity": validate_business_rules()
    }
```

## Processing Performance

### Throughput Targets
```yaml
Processing Volume:
  - Bronze ingestion: 1GB/hour raw data
  - Silver transformation: 500MB/hour normalized
  - Gold aggregation: 100MB/hour features
  - Database sync: 10k records/minute

Latency Requirements:
  - Bronze → Silver: < 30 minutes
  - Silver → Gold: < 15 minutes  
  - Database sync: < 5 minutes
  - End-to-end: < 1 hour
```

### Resource Scaling
```yaml
Light Processing (< 100MB/h):
  CPU: 1.0 vCPU
  Memory: 2GB
  
Heavy Processing (> 1GB/h):
  CPU: 4.0 vCPU
  Memory: 8GB
  
Peak Processing (> 5GB/h):
  CPU: 8.0 vCPU
  Memory: 16GB
  Parallel Workers: 8
```

## Health Monitoring

### Health Endpoint
```bash
GET http://localhost:8083/health

{
  "status": "healthy",
  "service": "data-connector",
  "timestamp": "2024-01-15T14:30:00Z",
  "components": {
    "s3_reader": {
      "status": "healthy",
      "last_read": "2024-01-15T14:25:00Z",
      "bucket_accessible": true,
      "pending_files": 15
    },
    "etl_pipeline": {
      "status": "processing",
      "active_jobs": 2,
      "completed_jobs_today": 24,
      "failed_jobs_today": 0,
      "avg_job_duration_minutes": 12
    },
    "database": {
      "status": "connected",
      "connection_pool_usage": 0.60,
      "last_write": "2024-01-15T14:29:30Z",
      "pending_writes": 500
    },
    "data_quality": {
      "status": "monitoring",
      "last_quality_check": "2024-01-15T14:20:00Z",
      "overall_quality_score": 0.97,
      "issues_detected": 2
    }
  }
}
```

### Key Metrics
- `data_connector_files_processed_total` - S3 files processed
- `data_connector_records_transformed_total` - Records ETL processed
- `data_connector_db_writes_total` - Database records written
- `data_connector_job_duration_seconds` - ETL job execution time
- `data_connector_quality_score` - Data quality percentage

## Operational Guidelines

### Service Dependencies
- **AWS S3** - Source and destination for data lake
- **Aurora PostgreSQL** - Application database
- **LocalStack** - Local development AWS simulation

### Error Handling
```python
ERROR_RECOVERY_STRATEGIES = {
    "s3_read_errors": "retry_with_exponential_backoff",
    "transformation_errors": "skip_record_and_log",
    "database_errors": "queue_for_retry",
    "schema_validation_errors": "quarantine_dataset",
    "resource_exhaustion": "scale_up_workers"
}
```

### Monitoring & Alerting
```yaml
Critical Alerts:
  - ETL jobs failing > 10% rate
  - Database connection lost > 5 minutes
  - Data quality score < 0.90
  - Processing lag > 2 hours

Warning Alerts:
  - Job duration > 1 hour
  - Data quality score < 0.95
  - Pending file count > 100
  - Memory usage > 85%
```

## Development

### Local Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Start infrastructure
docker-compose up localstack postgres -d

# Run service
CONFIG_FILE=config/local.yaml python src/main.py
```

### Testing
```bash
# Unit tests
pytest tests/unit/

# Integration tests (requires LocalStack + PostgreSQL)
pytest tests/integration/

# Data quality tests
pytest tests/quality/
```

This service operates as a comprehensive ETL engine that transforms raw Bitcoin market data into analysis-ready datasets while maintaining high data quality standards and providing reliable database integration for application consumption.