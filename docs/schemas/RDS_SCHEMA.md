# RDS Curated Layer Schema Documentation

## Overview

The RDS (Amazon Aurora PostgreSQL) layer serves as the **curated data store** for the Bitcoin price prediction pipeline. It provides optimized access for dashboards, operational monitoring, audit logs, and business intelligence while supporting the 10-second ahead prediction system with structured relational data.

## Database Architecture

### Purpose and Design
- **Operational Analytics**: Real-time dashboards and monitoring
- **Audit Trail**: Compliance and historical tracking
- **Business Intelligence**: Aggregated metrics and KPIs
- **Fast Queries**: Optimized for sub-second analytical queries
- **Data Integrity**: ACID properties and referential integrity

### Technology Stack
```
Amazon Aurora PostgreSQL 15.x
├── Multi-AZ Deployment
├── Read Replicas (3x for read scaling)
├── Automated Backups (7-day retention)
├── Performance Insights
└── Connection Pooling (PgBouncer)
```

## Database Schema Design

### 1. Core Market Data Tables

#### `market_data_minute` - Minute-level market summaries
```sql
CREATE TABLE market_data_minute (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL DEFAULT 'BTCUSDT',
    open_time BIGINT NOT NULL,                    -- Bar start time (epoch ms)
    close_time BIGINT NOT NULL,                   -- Bar end time (epoch ms)
    
    -- OHLCV Data
    open_price DECIMAL(20,8) NOT NULL,
    high_price DECIMAL(20,8) NOT NULL,
    low_price DECIMAL(20,8) NOT NULL,
    close_price DECIMAL(20,8) NOT NULL,
    volume DECIMAL(20,8) NOT NULL,
    notional DECIMAL(20,8) NOT NULL,
    
    -- Trade Statistics
    trade_count INTEGER NOT NULL,
    buy_trade_count INTEGER,
    sell_trade_count INTEGER,
    buy_volume DECIMAL(20,8),
    sell_volume DECIMAL(20,8),
    
    -- Computed Metrics
    vwap DECIMAL(20,8),                          -- Volume-weighted average price
    volume_imbalance DECIMAL(8,6),               -- (buy_vol - sell_vol) / total_vol
    price_change DECIMAL(20,8),                  -- close - open
    price_change_pct DECIMAL(8,6),               -- Price change percentage
    
    -- Data Quality
    completeness_score DECIMAL(4,3),             -- 0.000 - 1.000
    source_quality VARCHAR(20),                  -- 'sbe', 'rest', 'mixed', 'degraded'
    gap_seconds INTEGER DEFAULT 0,
    
    -- Metadata
    data_source VARCHAR(10) NOT NULL,            -- 'sbe' or 'rest'
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_prices CHECK (
        open_price > 0 AND high_price > 0 AND 
        low_price > 0 AND close_price > 0 AND
        high_price >= low_price
    ),
    CONSTRAINT valid_volume CHECK (volume >= 0 AND notional >= 0),
    CONSTRAINT valid_times CHECK (close_time > open_time),
    CONSTRAINT unique_symbol_time UNIQUE (symbol, open_time)
) PARTITION BY RANGE (open_time);

-- Partitioning for performance (monthly partitions)
CREATE TABLE market_data_minute_y2024m01 PARTITION OF market_data_minute
FOR VALUES FROM (1704067200000) TO (1706745600000);  -- Jan 2024

CREATE TABLE market_data_minute_y2024m02 PARTITION OF market_data_minute
FOR VALUES FROM (1706745600000) TO (1709251200000);  -- Feb 2024

-- Indexes for optimal query performance
CREATE INDEX idx_market_data_minute_symbol_time ON market_data_minute (symbol, open_time);
CREATE INDEX idx_market_data_minute_close_time ON market_data_minute (close_time);
CREATE INDEX idx_market_data_minute_created ON market_data_minute (created_at);
CREATE INDEX idx_market_data_minute_price ON market_data_minute (close_price);
```

#### `latest_market_state` - Current market snapshot
```sql
CREATE TABLE latest_market_state (
    symbol VARCHAR(20) PRIMARY KEY DEFAULT 'BTCUSDT',
    
    -- Current Prices
    price DECIMAL(20,8) NOT NULL,
    bid_price DECIMAL(20,8),
    ask_price DECIMAL(20,8),
    mid_price DECIMAL(20,8),
    spread DECIMAL(20,8),
    spread_bp DECIMAL(8,2),                      -- Spread in basis points
    
    -- Recent Volume
    volume_1s DECIMAL(20,8),
    volume_5s DECIMAL(20,8),
    volume_1m DECIMAL(20,8),
    volume_5m DECIMAL(20,8),
    
    -- Trade Flow
    trade_count_1s INTEGER,
    trade_count_5s INTEGER,
    trade_count_1m INTEGER,
    avg_trade_size_1s DECIMAL(20,8),
    
    -- Technical Indicators
    vwap_1m DECIMAL(20,8),
    vwap_5m DECIMAL(20,8),
    price_change_1m DECIMAL(20,8),
    price_change_pct_1m DECIMAL(8,6),
    volatility_1m DECIMAL(8,6),
    
    -- Order Book Metrics
    order_book_imbalance DECIMAL(8,6),
    bid_strength DECIMAL(20,8),
    ask_strength DECIMAL(20,8),
    
    -- Data Quality
    data_freshness_seconds INTEGER,
    last_trade_ts BIGINT NOT NULL,
    last_update_ts BIGINT NOT NULL,
    data_source VARCHAR(20) NOT NULL,
    
    -- Metadata
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_current_prices CHECK (
        price > 0 AND 
        (bid_price IS NULL OR bid_price > 0) AND
        (ask_price IS NULL OR ask_price > 0)
    ),
    CONSTRAINT valid_spread CHECK (
        (bid_price IS NULL OR ask_price IS NULL) OR 
        ask_price >= bid_price
    )
);

-- Real-time update trigger
CREATE OR REPLACE FUNCTION update_latest_market_state_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_latest_market_state_updated_at
    BEFORE UPDATE ON latest_market_state
    FOR EACH ROW
    EXECUTE FUNCTION update_latest_market_state_timestamp();
```

### 2. Prediction and Model Tables

#### `predictions_log` - All prediction records
```sql
CREATE TABLE predictions_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Prediction Identification
    prediction_id VARCHAR(50) NOT NULL,          -- Unique prediction identifier
    symbol VARCHAR(20) NOT NULL DEFAULT 'BTCUSDT',
    model_version VARCHAR(50) NOT NULL,
    
    -- Timing
    prediction_ts BIGINT NOT NULL,               -- When prediction was made (epoch ms)
    target_ts BIGINT NOT NULL,                   -- Target time (prediction_ts + 10s)
    
    -- Prediction Values
    current_price DECIMAL(20,8) NOT NULL,
    predicted_price DECIMAL(20,8) NOT NULL,
    price_change_predicted DECIMAL(20,8),       -- predicted_price - current_price
    return_predicted DECIMAL(10,8),             -- log(predicted_price / current_price)
    
    -- Confidence and Quality
    confidence DECIMAL(8,6) NOT NULL,           -- 0.000 - 1.000
    directional_confidence DECIMAL(8,6),
    magnitude_confidence DECIMAL(8,6),
    
    -- Performance Metrics
    inference_latency_ms INTEGER NOT NULL,
    feature_read_latency_ms INTEGER,
    model_inference_latency_ms INTEGER,
    total_processing_ms INTEGER,
    
    -- Input Quality
    features_age_ms INTEGER NOT NULL,
    feature_completeness DECIMAL(4,3),          -- 0.000 - 1.000
    data_sources VARCHAR(50),                   -- 'redis', 'fallback', etc.
    
    -- Actual Outcomes (populated after target_ts)
    actual_price DECIMAL(20,8),
    actual_price_change DECIMAL(20,8),
    actual_return DECIMAL(10,8),
    prediction_error DECIMAL(20,8),             -- actual_price - predicted_price
    absolute_error DECIMAL(20,8),               -- abs(prediction_error)
    squared_error DECIMAL(20,8),                -- prediction_error^2
    directional_correct BOOLEAN,                -- True if direction predicted correctly
    
    -- Analysis Fields
    market_regime VARCHAR(20),                  -- 'normal', 'volatile', 'trending'
    prediction_bucket VARCHAR(20),              -- 'small', 'medium', 'large' move
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    outcome_updated_at TIMESTAMP,               -- When actual outcome was recorded
    
    -- Constraints
    CONSTRAINT valid_prediction_times CHECK (target_ts > prediction_ts),
    CONSTRAINT valid_confidence CHECK (confidence >= 0 AND confidence <= 1),
    CONSTRAINT valid_latency CHECK (inference_latency_ms >= 0),
    CONSTRAINT valid_prices CHECK (current_price > 0 AND predicted_price > 0)
    
) PARTITION BY RANGE (prediction_ts);

-- Monthly partitions for predictions
CREATE TABLE predictions_log_y2024m01 PARTITION OF predictions_log
FOR VALUES FROM (1704067200000) TO (1706745600000);

-- Indexes for prediction analysis
CREATE INDEX idx_predictions_symbol_pred_ts ON predictions_log (symbol, prediction_ts);
CREATE INDEX idx_predictions_target_ts ON predictions_log (target_ts);
CREATE INDEX idx_predictions_model_version ON predictions_log (model_version);
CREATE INDEX idx_predictions_confidence ON predictions_log (confidence);
CREATE INDEX idx_predictions_error ON predictions_log (absolute_error) WHERE actual_price IS NOT NULL;
CREATE INDEX idx_predictions_directional ON predictions_log (directional_correct) WHERE directional_correct IS NOT NULL;
```

#### `model_performance` - Model performance tracking
```sql
CREATE TABLE model_performance (
    id BIGSERIAL PRIMARY KEY,
    
    -- Model Information
    model_version VARCHAR(50) NOT NULL,
    evaluation_period_start BIGINT NOT NULL,
    evaluation_period_end BIGINT NOT NULL,
    
    -- Sample Size
    total_predictions INTEGER NOT NULL,
    valid_predictions INTEGER NOT NULL,         -- Predictions with actual outcomes
    
    -- Accuracy Metrics
    mean_absolute_error DECIMAL(10,6),          -- Average absolute error
    root_mean_squared_error DECIMAL(10,6),      -- RMSE
    mean_absolute_percentage_error DECIMAL(8,6), -- MAPE
    directional_accuracy DECIMAL(8,6),          -- Percentage of correct directions
    
    -- Distribution Metrics
    prediction_correlation DECIMAL(8,6),        -- Correlation with actual prices
    bias DECIMAL(10,6),                         -- Average prediction error (bias)
    
    -- Performance by Confidence
    high_confidence_accuracy DECIMAL(8,6),      -- Accuracy for confidence > 0.8
    medium_confidence_accuracy DECIMAL(8,6),    -- Accuracy for 0.5 < confidence <= 0.8
    low_confidence_accuracy DECIMAL(8,6),       -- Accuracy for confidence <= 0.5
    
    -- Performance by Market Conditions
    normal_market_accuracy DECIMAL(8,6),
    volatile_market_accuracy DECIMAL(8,6),
    trending_market_accuracy DECIMAL(8,6),
    
    -- Latency Metrics
    avg_inference_latency_ms DECIMAL(8,2),
    p95_inference_latency_ms DECIMAL(8,2),
    p99_inference_latency_ms DECIMAL(8,2),
    
    -- Business Metrics
    profitable_predictions_pct DECIMAL(8,6),    -- Predictions that would be profitable
    sharpe_ratio DECIMAL(8,6),                  -- Risk-adjusted return metric
    
    -- Metadata
    evaluated_at TIMESTAMP DEFAULT NOW(),
    notes TEXT,
    
    -- Constraints
    CONSTRAINT valid_period CHECK (evaluation_period_end > evaluation_period_start),
    CONSTRAINT valid_sample_size CHECK (valid_predictions <= total_predictions),
    CONSTRAINT valid_accuracy_metrics CHECK (
        directional_accuracy >= 0 AND directional_accuracy <= 1
    )
);

-- Indexes for model performance analysis
CREATE INDEX idx_model_performance_version ON model_performance (model_version);
CREATE INDEX idx_model_performance_period ON model_performance (evaluation_period_start, evaluation_period_end);
CREATE INDEX idx_model_performance_evaluated ON model_performance (evaluated_at);
```

### 3. Service Health and Monitoring

#### `service_health_log` - Service health monitoring
```sql
CREATE TABLE service_health_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Service Information
    service_name VARCHAR(50) NOT NULL,
    service_version VARCHAR(20),
    instance_id VARCHAR(100),
    
    -- Health Status
    health_status VARCHAR(20) NOT NULL,         -- 'healthy', 'degraded', 'unhealthy'
    status_details JSONB,                       -- Detailed status information
    
    -- Performance Metrics
    latency_p50_ms DECIMAL(10,2),
    latency_p95_ms DECIMAL(10,2),
    latency_p99_ms DECIMAL(10,2),
    error_rate DECIMAL(8,6),                    -- 0.000 - 1.000
    
    -- Resource Utilization
    cpu_usage_percent DECIMAL(5,2),
    memory_usage_mb DECIMAL(10,2),
    memory_usage_percent DECIMAL(5,2),
    
    -- Service-Specific Metrics
    throughput_per_second DECIMAL(10,2),
    active_connections INTEGER,
    queue_depth INTEGER,
    
    -- Redis-specific (for aggregator/inference services)
    redis_hit_rate DECIMAL(8,6),
    redis_avg_latency_ms DECIMAL(8,2),
    redis_connection_pool_usage DECIMAL(8,6),
    
    -- Prediction-specific (for inference service)
    predictions_per_minute INTEGER,
    feature_freshness_ms INTEGER,
    model_load_status VARCHAR(20),
    
    -- SBE-specific (for ingestor service)
    sbe_events_per_second DECIMAL(10,2),
    sbe_connection_status VARCHAR(20),
    sequence_gaps_detected INTEGER,
    
    -- Data Quality
    data_completeness DECIMAL(8,6),
    data_staleness_seconds INTEGER,
    
    -- Timing
    check_timestamp BIGINT NOT NULL,            -- When health check was performed
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_health_status CHECK (
        health_status IN ('healthy', 'degraded', 'unhealthy')
    ),
    CONSTRAINT valid_percentages CHECK (
        (error_rate IS NULL OR (error_rate >= 0 AND error_rate <= 1)) AND
        (cpu_usage_percent IS NULL OR (cpu_usage_percent >= 0 AND cpu_usage_percent <= 100)) AND
        (memory_usage_percent IS NULL OR (memory_usage_percent >= 0 AND memory_usage_percent <= 100))
    )
    
) PARTITION BY RANGE (check_timestamp);

-- Daily partitions for health logs
CREATE TABLE service_health_log_y2024m01d01 PARTITION OF service_health_log
FOR VALUES FROM (1704067200000) TO (1704153600000);

-- Indexes for monitoring queries
CREATE INDEX idx_service_health_service_timestamp ON service_health_log (service_name, check_timestamp);
CREATE INDEX idx_service_health_status ON service_health_log (health_status);
CREATE INDEX idx_service_health_created ON service_health_log (created_at);
```

#### `system_alerts` - Alert and incident tracking
```sql
CREATE TABLE system_alerts (
    id BIGSERIAL PRIMARY KEY,
    
    -- Alert Information
    alert_id VARCHAR(100) NOT NULL,             -- Unique alert identifier
    alert_type VARCHAR(50) NOT NULL,            -- 'latency', 'error_rate', 'downtime', etc.
    severity VARCHAR(20) NOT NULL,              -- 'critical', 'warning', 'info'
    title VARCHAR(200) NOT NULL,
    description TEXT,
    
    -- Source Information
    service_name VARCHAR(50),
    component VARCHAR(50),
    metric_name VARCHAR(100),
    
    -- Alert Values
    threshold_value DECIMAL(20,8),
    actual_value DECIMAL(20,8),
    alert_condition VARCHAR(50),               -- 'greater_than', 'less_than', 'equals'
    
    -- Timing
    triggered_at BIGINT NOT NULL,
    resolved_at BIGINT,
    acknowledged_at BIGINT,
    
    -- Status
    status VARCHAR(20) DEFAULT 'active',       -- 'active', 'resolved', 'acknowledged'
    
    -- Resolution
    resolved_by VARCHAR(100),
    resolution_notes TEXT,
    auto_resolved BOOLEAN DEFAULT FALSE,
    
    -- Notification
    notification_sent BOOLEAN DEFAULT FALSE,
    notification_channels VARCHAR(200),        -- 'slack', 'email', 'pagerduty'
    
    -- Metadata
    additional_context JSONB,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_severity CHECK (severity IN ('critical', 'warning', 'info')),
    CONSTRAINT valid_status CHECK (status IN ('active', 'resolved', 'acknowledged')),
    CONSTRAINT valid_timing CHECK (
        (resolved_at IS NULL OR resolved_at >= triggered_at) AND
        (acknowledged_at IS NULL OR acknowledged_at >= triggered_at)
    )
);

-- Indexes for alert management
CREATE INDEX idx_system_alerts_triggered ON system_alerts (triggered_at);
CREATE INDEX idx_system_alerts_status ON system_alerts (status);
CREATE INDEX idx_system_alerts_service ON system_alerts (service_name);
CREATE INDEX idx_system_alerts_severity ON system_alerts (severity);
CREATE INDEX idx_system_alerts_active ON system_alerts (status, triggered_at) WHERE status = 'active';
```

### 4. Business Intelligence and Analytics

#### `daily_trading_summary` - Daily market summaries
```sql
CREATE TABLE daily_trading_summary (
    id BIGSERIAL PRIMARY KEY,
    
    -- Date Information
    trading_date DATE NOT NULL,
    symbol VARCHAR(20) NOT NULL DEFAULT 'BTCUSDT',
    
    -- OHLCV Summary
    open_price DECIMAL(20,8) NOT NULL,
    high_price DECIMAL(20,8) NOT NULL,
    low_price DECIMAL(20,8) NOT NULL,
    close_price DECIMAL(20,8) NOT NULL,
    volume_24h DECIMAL(20,8) NOT NULL,
    notional_24h DECIMAL(20,8) NOT NULL,
    
    -- Price Movement
    price_change_24h DECIMAL(20,8),
    price_change_pct_24h DECIMAL(8,6),
    price_range_24h DECIMAL(20,8),              -- high - low
    
    -- Trading Activity
    total_trades INTEGER,
    avg_trade_size DECIMAL(20,8),
    largest_trade DECIMAL(20,8),
    
    -- Volatility Metrics
    volatility_24h DECIMAL(8,6),
    vwap_24h DECIMAL(20,8),
    
    -- Prediction Performance (for this day)
    predictions_made INTEGER,
    prediction_accuracy DECIMAL(8,6),
    avg_prediction_error DECIMAL(20,8),
    model_version_used VARCHAR(50),
    
    -- Data Quality
    uptime_minutes INTEGER,                     -- Minutes of data availability
    data_completeness DECIMAL(8,6),
    gap_count INTEGER,
    total_gap_minutes INTEGER,
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT unique_symbol_date UNIQUE (symbol, trading_date),
    CONSTRAINT valid_daily_prices CHECK (
        open_price > 0 AND high_price > 0 AND 
        low_price > 0 AND close_price > 0 AND
        high_price >= low_price
    )
);

-- Indexes for BI queries
CREATE INDEX idx_daily_summary_date ON daily_trading_summary (trading_date);
CREATE INDEX idx_daily_summary_symbol_date ON daily_trading_summary (symbol, trading_date);
```

#### `model_deployment_log` - Model deployment tracking
```sql
CREATE TABLE model_deployment_log (
    id BIGSERIAL PRIMARY KEY,
    
    -- Model Information
    model_version VARCHAR(50) NOT NULL,
    model_file_path VARCHAR(500),
    model_hash VARCHAR(64),                     -- SHA-256 hash of model file
    
    -- Deployment Information
    deployment_type VARCHAR(20) NOT NULL,      -- 'initial', 'upgrade', 'rollback', 'hotfix'
    deployment_status VARCHAR(20) NOT NULL,    -- 'deploying', 'active', 'inactive', 'failed'
    
    -- Traffic Configuration
    traffic_percentage INTEGER DEFAULT 100,     -- Percentage of traffic for A/B testing
    canary_deployment BOOLEAN DEFAULT FALSE,
    
    -- Performance Requirements
    target_latency_ms INTEGER,
    target_accuracy DECIMAL(8,6),
    
    -- Deployment Timing
    deployment_started_at BIGINT NOT NULL,
    deployment_completed_at BIGINT,
    activation_at BIGINT,
    deactivation_at BIGINT,
    
    -- Validation Results
    validation_passed BOOLEAN,
    validation_results JSONB,
    performance_test_results JSONB,
    
    -- Deployment Details
    deployed_by VARCHAR(100),
    deployment_notes TEXT,
    rollback_reason TEXT,
    
    -- Previous Model (for rollbacks)
    previous_model_version VARCHAR(50),
    
    -- Metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_deployment_status CHECK (
        deployment_status IN ('deploying', 'active', 'inactive', 'failed')
    ),
    CONSTRAINT valid_deployment_type CHECK (
        deployment_type IN ('initial', 'upgrade', 'rollback', 'hotfix')
    ),
    CONSTRAINT valid_traffic_percentage CHECK (
        traffic_percentage >= 0 AND traffic_percentage <= 100
    )
);

-- Indexes for deployment tracking
CREATE INDEX idx_model_deployment_version ON model_deployment_log (model_version);
CREATE INDEX idx_model_deployment_status ON model_deployment_log (deployment_status);
CREATE INDEX idx_model_deployment_started ON model_deployment_log (deployment_started_at);
```

## Views and Analytics

### 1. Real-time Dashboard Views

#### Current System Health View
```sql
CREATE OR REPLACE VIEW current_system_health AS
WITH latest_health AS (
    SELECT DISTINCT ON (service_name)
        service_name,
        health_status,
        latency_p99_ms,
        error_rate,
        cpu_usage_percent,
        memory_usage_percent,
        redis_hit_rate,
        predictions_per_minute,
        feature_freshness_ms,
        check_timestamp
    FROM service_health_log
    ORDER BY service_name, check_timestamp DESC
)
SELECT 
    service_name,
    health_status,
    CASE 
        WHEN health_status = 'healthy' THEN 1
        WHEN health_status = 'degraded' THEN 0.5
        ELSE 0
    END as health_score,
    latency_p99_ms,
    error_rate,
    cpu_usage_percent,
    memory_usage_percent,
    redis_hit_rate,
    predictions_per_minute,
    feature_freshness_ms,
    EXTRACT(EPOCH FROM NOW()) * 1000 - check_timestamp as staleness_ms
FROM latest_health;
```

#### Recent Prediction Performance View
```sql
CREATE OR REPLACE VIEW recent_prediction_performance AS
WITH recent_predictions AS (
    SELECT *
    FROM predictions_log
    WHERE prediction_ts > EXTRACT(EPOCH FROM NOW() - INTERVAL '1 hour') * 1000
      AND actual_price IS NOT NULL
)
SELECT
    COUNT(*) as total_predictions,
    AVG(absolute_error) as avg_absolute_error,
    SQRT(AVG(squared_error)) as rmse,
    AVG(CASE WHEN directional_correct THEN 1.0 ELSE 0.0 END) as directional_accuracy,
    AVG(confidence) as avg_confidence,
    AVG(inference_latency_ms) as avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY inference_latency_ms) as p95_latency_ms,
    PERCENTILE_CONT(0.99) WITHIN GROUP (ORDER BY inference_latency_ms) as p99_latency_ms,
    MIN(prediction_ts) as period_start,
    MAX(prediction_ts) as period_end
FROM recent_predictions;
```

### 2. Analytics and Reporting Views

#### Model Performance Comparison View
```sql
CREATE OR REPLACE VIEW model_performance_comparison AS
WITH model_stats AS (
    SELECT 
        model_version,
        COUNT(*) as predictions_count,
        AVG(absolute_error) as avg_error,
        AVG(CASE WHEN directional_correct THEN 1.0 ELSE 0.0 END) as accuracy,
        AVG(confidence) as avg_confidence,
        AVG(inference_latency_ms) as avg_latency,
        MIN(prediction_ts) as first_prediction,
        MAX(prediction_ts) as last_prediction
    FROM predictions_log
    WHERE actual_price IS NOT NULL
      AND prediction_ts > EXTRACT(EPOCH FROM NOW() - INTERVAL '7 days') * 1000
    GROUP BY model_version
)
SELECT 
    model_version,
    predictions_count,
    ROUND(avg_error::numeric, 4) as avg_absolute_error,
    ROUND(accuracy::numeric, 4) as directional_accuracy,
    ROUND(avg_confidence::numeric, 3) as avg_confidence,
    ROUND(avg_latency::numeric, 1) as avg_latency_ms,
    TO_TIMESTAMP(first_prediction / 1000) as first_prediction_at,
    TO_TIMESTAMP(last_prediction / 1000) as last_prediction_at
FROM model_stats
ORDER BY last_prediction DESC;
```

#### Daily Trading Analytics View
```sql
CREATE OR REPLACE VIEW daily_trading_analytics AS
SELECT 
    trading_date,
    symbol,
    open_price,
    high_price,
    low_price,
    close_price,
    price_change_24h,
    price_change_pct_24h,
    volume_24h,
    total_trades,
    volatility_24h,
    predictions_made,
    prediction_accuracy,
    data_completeness,
    CASE 
        WHEN ABS(price_change_pct_24h) > 0.05 THEN 'high_volatility'
        WHEN ABS(price_change_pct_24h) > 0.02 THEN 'medium_volatility'
        ELSE 'low_volatility'
    END as volatility_category,
    CASE
        WHEN prediction_accuracy > 0.6 THEN 'good'
        WHEN prediction_accuracy > 0.5 THEN 'fair'
        ELSE 'poor'
    END as prediction_performance
FROM daily_trading_summary
WHERE trading_date >= CURRENT_DATE - INTERVAL '30 days'
ORDER BY trading_date DESC;
```

## Stored Procedures and Functions

### 1. Data Management Procedures

#### Update Prediction Outcomes
```sql
CREATE OR REPLACE FUNCTION update_prediction_outcomes()
RETURNS INTEGER AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    -- Update predictions where target time has passed but outcome not yet recorded
    WITH target_predictions AS (
        SELECT p.id, p.target_ts, p.predicted_price, p.current_price
        FROM predictions_log p
        WHERE p.actual_price IS NULL
          AND p.target_ts <= EXTRACT(EPOCH FROM NOW()) * 1000
          AND p.target_ts > EXTRACT(EPOCH FROM NOW() - INTERVAL '1 day') * 1000
    ),
    actual_prices AS (
        SELECT 
            tp.id,
            COALESCE(
                -- Try to find exact timestamp match
                (SELECT close_price FROM market_data_minute 
                 WHERE open_time <= tp.target_ts AND close_time > tp.target_ts
                 LIMIT 1),
                -- Fallback to closest price
                (SELECT close_price FROM market_data_minute 
                 WHERE ABS(close_time - tp.target_ts) = (
                     SELECT MIN(ABS(close_time - tp.target_ts)) 
                     FROM market_data_minute 
                     WHERE close_time BETWEEN tp.target_ts - 30000 AND tp.target_ts + 30000
                 )
                 LIMIT 1)
            ) as actual_price
        FROM target_predictions tp
    )
    UPDATE predictions_log 
    SET 
        actual_price = ap.actual_price,
        actual_price_change = ap.actual_price - predictions_log.current_price,
        actual_return = LN(ap.actual_price / predictions_log.current_price),
        prediction_error = ap.actual_price - predictions_log.predicted_price,
        absolute_error = ABS(ap.actual_price - predictions_log.predicted_price),
        squared_error = POWER(ap.actual_price - predictions_log.predicted_price, 2),
        directional_correct = (
            SIGN(ap.actual_price - predictions_log.current_price) = 
            SIGN(predictions_log.predicted_price - predictions_log.current_price)
        ),
        outcome_updated_at = NOW()
    FROM actual_prices ap
    WHERE predictions_log.id = ap.id
      AND ap.actual_price IS NOT NULL;
    
    GET DIAGNOSTICS updated_count = ROW_COUNT;
    
    RETURN updated_count;
END;
$$ LANGUAGE plpgsql;
```

#### Calculate Model Performance
```sql
CREATE OR REPLACE FUNCTION calculate_model_performance(
    p_model_version VARCHAR(50),
    p_start_time BIGINT,
    p_end_time BIGINT
) RETURNS TABLE (
    total_predictions INTEGER,
    valid_predictions INTEGER,
    mean_absolute_error DECIMAL(10,6),
    rmse DECIMAL(10,6),
    directional_accuracy DECIMAL(8,6),
    correlation DECIMAL(8,6)
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        COUNT(*)::INTEGER as total_predictions,
        COUNT(CASE WHEN actual_price IS NOT NULL THEN 1 END)::INTEGER as valid_predictions,
        AVG(absolute_error)::DECIMAL(10,6) as mean_absolute_error,
        SQRT(AVG(squared_error))::DECIMAL(10,6) as rmse,
        AVG(CASE WHEN directional_correct THEN 1.0 ELSE 0.0 END)::DECIMAL(8,6) as directional_accuracy,
        CORR(predicted_price, actual_price)::DECIMAL(8,6) as correlation
    FROM predictions_log
    WHERE model_version = p_model_version
      AND prediction_ts BETWEEN p_start_time AND p_end_time
      AND actual_price IS NOT NULL;
END;
$$ LANGUAGE plpgsql;
```

### 2. Monitoring Functions

#### Check System Health
```sql
CREATE OR REPLACE FUNCTION check_system_health()
RETURNS TABLE (
    overall_status VARCHAR(20),
    unhealthy_services TEXT[],
    high_latency_services TEXT[],
    stale_data_services TEXT[]
) AS $$
DECLARE
    v_overall_status VARCHAR(20) := 'healthy';
    v_unhealthy_services TEXT[] := '{}';
    v_high_latency_services TEXT[] := '{}';
    v_stale_data_services TEXT[] := '{}';
BEGIN
    -- Check for unhealthy services
    SELECT ARRAY_AGG(service_name)
    INTO v_unhealthy_services
    FROM current_system_health
    WHERE health_status IN ('unhealthy', 'degraded');
    
    -- Check for high latency services
    SELECT ARRAY_AGG(service_name)
    INTO v_high_latency_services
    FROM current_system_health
    WHERE latency_p99_ms > 100;  -- 100ms threshold
    
    -- Check for stale data
    SELECT ARRAY_AGG(service_name)
    INTO v_stale_data_services
    FROM current_system_health
    WHERE staleness_ms > 60000;  -- 1 minute threshold
    
    -- Determine overall status
    IF ARRAY_LENGTH(v_unhealthy_services, 1) > 0 THEN
        v_overall_status := 'unhealthy';
    ELSIF ARRAY_LENGTH(v_high_latency_services, 1) > 0 OR 
          ARRAY_LENGTH(v_stale_data_services, 1) > 0 THEN
        v_overall_status := 'degraded';
    END IF;
    
    RETURN QUERY SELECT 
        v_overall_status,
        v_unhealthy_services,
        v_high_latency_services,
        v_stale_data_services;
END;
$$ LANGUAGE plpgsql;
```

## Database Configuration and Optimization

### 1. Performance Tuning
```sql
-- Connection and memory settings
ALTER SYSTEM SET max_connections = 200;
ALTER SYSTEM SET shared_buffers = '4GB';
ALTER SYSTEM SET effective_cache_size = '12GB';
ALTER SYSTEM SET work_mem = '64MB';
ALTER SYSTEM SET maintenance_work_mem = '512MB';

-- Query optimization
ALTER SYSTEM SET random_page_cost = 1.1;  -- SSD optimization
ALTER SYSTEM SET effective_io_concurrency = 200;
ALTER SYSTEM SET checkpoint_completion_target = 0.9;

-- Logging and monitoring
ALTER SYSTEM SET log_min_duration_statement = 1000;  -- Log slow queries
ALTER SYSTEM SET log_checkpoints = on;
ALTER SYSTEM SET log_connections = on;
ALTER SYSTEM SET log_disconnections = on;

SELECT pg_reload_conf();
```

### 2. Maintenance Jobs
```sql
-- Auto-vacuum configuration
ALTER TABLE predictions_log SET (
    autovacuum_vacuum_scale_factor = 0.1,
    autovacuum_analyze_scale_factor = 0.05
);

-- Partition management (example for monthly partitions)
CREATE OR REPLACE FUNCTION create_monthly_partitions()
RETURNS VOID AS $$
DECLARE
    start_date DATE;
    end_date DATE;
    partition_name TEXT;
    start_epoch BIGINT;
    end_epoch BIGINT;
BEGIN
    -- Create partitions for next 3 months
    FOR i IN 0..2 LOOP
        start_date := DATE_TRUNC('month', CURRENT_DATE + (i || ' months')::INTERVAL);
        end_date := start_date + INTERVAL '1 month';
        start_epoch := EXTRACT(EPOCH FROM start_date) * 1000;
        end_epoch := EXTRACT(EPOCH FROM end_date) * 1000;
        
        -- Market data partitions
        partition_name := 'market_data_minute_' || TO_CHAR(start_date, 'YYYY_MM');
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I PARTITION OF market_data_minute
            FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_epoch, end_epoch);
        
        -- Predictions partitions
        partition_name := 'predictions_log_' || TO_CHAR(start_date, 'YYYY_MM');
        EXECUTE format('
            CREATE TABLE IF NOT EXISTS %I PARTITION OF predictions_log
            FOR VALUES FROM (%L) TO (%L)',
            partition_name, start_epoch, end_epoch);
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Schedule partition creation (to be run monthly)
-- SELECT create_monthly_partitions();
```

## Backup and Recovery

### 1. Backup Strategy
```sql
-- Point-in-time recovery configuration
ALTER SYSTEM SET wal_level = 'replica';
ALTER SYSTEM SET archive_mode = 'on';
ALTER SYSTEM SET archive_command = 'aws s3 cp %p s3://bitcoin-db-backups/wal/%f';

-- Backup retention
-- Daily automated backups with 7-day retention
-- Weekly backups with 4-week retention  
-- Monthly backups with 12-month retention
```

### 2. Data Retention Policies
```sql
-- Clean up old partitions (automated job)
CREATE OR REPLACE FUNCTION cleanup_old_partitions()
RETURNS INTEGER AS $$
DECLARE
    partition_record RECORD;
    cutoff_date DATE;
    deleted_count INTEGER := 0;
BEGIN
    -- Keep 90 days of detailed data
    cutoff_date := CURRENT_DATE - INTERVAL '90 days';
    
    -- Drop old partitions
    FOR partition_record IN
        SELECT schemaname, tablename
        FROM pg_tables
        WHERE tablename LIKE 'predictions_log_%'
           OR tablename LIKE 'market_data_minute_%'
           OR tablename LIKE 'service_health_log_%'
    LOOP
        -- Extract date from partition name and check if old
        -- Implementation depends on naming convention
        -- EXECUTE format('DROP TABLE IF EXISTS %I.%I', 
        --               partition_record.schemaname, partition_record.tablename);
        -- deleted_count := deleted_count + 1;
    END LOOP;
    
    RETURN deleted_count;
END;
$$ LANGUAGE plpgsql;
```

This RDS schema provides comprehensive operational analytics, monitoring, and business intelligence capabilities for the Bitcoin prediction pipeline while maintaining optimal performance through proper indexing, partitioning, and query optimization strategies.