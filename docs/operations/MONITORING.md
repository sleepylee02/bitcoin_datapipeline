# Bitcoin Pipeline Monitoring Documentation

## Overview

Comprehensive monitoring for the **10-second ahead Bitcoin price prediction pipeline** with **sub-100ms inference latency** requirements. This document defines critical metrics, alerting strategies, and observability practices for the hot path architecture with atomic re-anchoring reliability.

## Monitoring Philosophy

### 1. Hot Path First
- **Inference Latency**: P99 <100ms is non-negotiable
- **Prediction Frequency**: Exactly every 2 seconds
- **Feature Freshness**: <2s for optimal predictions
- **Zero Tolerance**: Hot path degradation triggers immediate alerts

### 2. Reliability Monitoring
- **Atomic Operations**: Monitor re-anchoring success rates
- **Gap Detection**: Track SBE stream continuity
- **Recovery Speed**: Re-anchor operations <60s
- **Data Integrity**: Validation across all layers

### 3. Business Impact
- **Prediction Accuracy**: 10-second directional accuracy >55%
- **Service Availability**: 99.9% uptime target
- **Cost Efficiency**: Monitor AWS resource utilization
- **User Experience**: End-to-end latency tracking

## Critical Metrics Hierarchy

### Tier 1: Business Critical (Immediate PagerDuty)
```
Metric                           Threshold    Impact
─────────────────────────────────────────────────────────
Inference P99 Latency           >100ms       Revenue loss
Prediction Frequency Deviation  >10%         Model degradation
Service Availability            <99.9%       Business downtime
Data Pipeline Failure           Any          Prediction halt
Redis Cluster Failure           Any          Hot path down
```

### Tier 2: Performance Degradation (Slack Alerts)
```
Metric                           Threshold    Impact
─────────────────────────────────────────────────────────
Feature Freshness               >5s          Accuracy loss
Prediction Accuracy Drop        >20%         Model issue
Re-anchor Duration              >60s         Extended recovery
SBE Stream Disconnection        >30s         Data gaps
Model Loading Failure           Any          Fallback mode
```

### Tier 3: Operational Monitoring (Dashboard Only)
```
Metric                           Threshold    Impact
─────────────────────────────────────────────────────────
Memory Usage                    >80%         Resource planning
CPU Utilization                 >70%         Scaling needed
Network Latency                 >50ms        Infrastructure
Storage Usage                   >85%         Capacity planning
```

## Service-Specific Monitoring

### 1. Inference Service (Hot Path)

#### Critical Hot Path Metrics
```yaml
hot_path_metrics:
  # Latency Requirements (P99 <100ms)
  inference_total_latency_seconds:
    description: "End-to-end prediction latency"
    type: histogram
    buckets: [0.001, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5]
    alerts:
      - name: "Inference Latency P99 High"
        condition: "histogram_quantile(0.99, rate(inference_total_latency_seconds_bucket[2m])) > 0.1"
        severity: "critical"
        
  inference_redis_read_duration_seconds:
    description: "Redis feature read time"
    type: histogram
    buckets: [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]
    alerts:
      - name: "Redis Read Latency High"
        condition: "histogram_quantile(0.95, rate(inference_redis_read_duration_seconds_bucket[1m])) > 0.005"
        severity: "warning"
        
  inference_model_prediction_duration_seconds:
    description: "Model inference time"
    type: histogram
    buckets: [0.001, 0.005, 0.01, 0.02, 0.03, 0.05, 0.1]
    alerts:
      - name: "Model Inference Slow"
        condition: "histogram_quantile(0.95, rate(inference_model_prediction_duration_seconds_bucket[1m])) > 0.03"
        severity: "warning"

  # Prediction Frequency (Every 2 seconds)
  inference_predictions_total:
    description: "Total predictions generated"
    type: counter
    alerts:
      - name: "Prediction Frequency Low"
        condition: "rate(inference_predictions_total[2m]) < 0.4"  # <0.4 predictions/sec
        severity: "critical"
      - name: "Prediction Frequency High"
        condition: "rate(inference_predictions_total[2m]) > 0.6"  # >0.6 predictions/sec
        severity: "warning"

  # Feature Quality
  inference_feature_age_seconds:
    description: "Age of input features"
    type: histogram
    buckets: [0.5, 1, 2, 3, 5, 10, 30]
    alerts:
      - name: "Stale Features"
        condition: "histogram_quantile(0.95, rate(inference_feature_age_seconds_bucket[1m])) > 5"
        severity: "warning"
        
  inference_feature_completeness:
    description: "Feature completeness score"
    type: histogram
    buckets: [0.5, 0.7, 0.8, 0.9, 0.95, 0.98, 1.0]
    alerts:
      - name: "Incomplete Features"
        condition: "histogram_quantile(0.95, rate(inference_feature_completeness_bucket[5m])) < 0.9"
        severity: "warning"

  # Model Performance
  inference_confidence_score:
    description: "Prediction confidence distribution"
    type: histogram
    buckets: [0.1, 0.3, 0.5, 0.7, 0.8, 0.9, 0.95, 1.0]
    
  inference_fallback_predictions_total:
    description: "Fallback predictions used"
    type: counter
    alerts:
      - name: "High Fallback Rate"
        condition: "rate(inference_fallback_predictions_total[5m]) / rate(inference_predictions_total[5m]) > 0.1"
        severity: "warning"
```

#### Health Check Endpoint Monitoring
```python
# /health endpoint monitoring
HEALTH_CHECK_METRICS = {
    "model_status": {
        "healthy": "Model loaded and ready",
        "degraded": "Model loaded but performance issues",
        "unhealthy": "Model loading failed"
    },
    "redis_connectivity": {
        "connected": "Redis connection active",
        "degraded": "Redis connection issues",
        "disconnected": "Redis unavailable"
    },
    "feature_pipeline": {
        "active": "Features updating normally",
        "stale": "Features older than 5s",
        "failed": "Feature pipeline error"
    }
}

# Alert on health check failures
health_check_failed:
  description: "Service health check failing"
  condition: "up{job='inference-service'} == 0"
  severity: "critical"
```

### 2. Aggregator Service (State Management)

#### Redis State Management Metrics
```yaml
aggregator_metrics:
  # Redis Operations
  aggregator_redis_operations_total:
    description: "Redis operations performed"
    type: counter
    labels: ["operation", "key_type"]
    alerts:
      - name: "Redis Operation Failures"
        condition: "rate(aggregator_redis_operations_total{status='error'}[5m]) > 10"
        severity: "critical"
        
  aggregator_redis_operation_duration_seconds:
    description: "Redis operation latency"
    type: histogram
    buckets: [0.0001, 0.0005, 0.001, 0.002, 0.005, 0.01]
    alerts:
      - name: "Redis Operations Slow"
        condition: "histogram_quantile(0.95, rate(aggregator_redis_operation_duration_seconds_bucket[2m])) > 0.005"
        severity: "warning"

  # Feature Computation
  aggregator_feature_updates_total:
    description: "Feature vector updates"
    type: counter
    alerts:
      - name: "Feature Updates Stopped"
        condition: "rate(aggregator_feature_updates_total[5m]) == 0"
        severity: "critical"
        
  aggregator_feature_computation_duration_seconds:
    description: "Feature computation time"
    type: histogram
    buckets: [0.001, 0.005, 0.01, 0.02, 0.05]
    alerts:
      - name: "Feature Computation Slow"
        condition: "histogram_quantile(0.95, rate(aggregator_feature_computation_duration_seconds_bucket[2m])) > 0.02"
        severity: "warning"

  # Kinesis Processing
  aggregator_kinesis_records_processed_total:
    description: "Kinesis records processed"
    type: counter
    labels: ["stream", "status"]
    
  aggregator_kinesis_lag_seconds:
    description: "Kinesis processing lag"
    type: gauge
    alerts:
      - name: "Kinesis Processing Lag"
        condition: "aggregator_kinesis_lag_seconds > 10"
        severity: "warning"

  # Re-anchoring Operations
  aggregator_reanchor_operations_total:
    description: "Re-anchor operations performed"
    type: counter
    labels: ["status"]
    
  aggregator_reanchor_duration_seconds:
    description: "Re-anchor operation duration"
    type: histogram
    buckets: [5, 10, 20, 30, 60, 120]
    alerts:
      - name: "Re-anchor Duration High"
        condition: "histogram_quantile(0.95, rate(aggregator_reanchor_duration_seconds_bucket[10m])) > 60"
        severity: "warning"
      - name: "Re-anchor Failed"
        condition: "increase(aggregator_reanchor_operations_total{status='failed'}[5m]) > 0"
        severity: "critical"
```

### 3. Ingestor Service (Data Collection)

#### SBE Stream Monitoring
```yaml
ingestor_sbe_metrics:
  # Stream Health
  ingestor_sbe_connection_status:
    description: "SBE WebSocket connection status"
    type: gauge
    values: [0=disconnected, 1=connected]
    alerts:
      - name: "SBE Stream Disconnected"
        condition: "ingestor_sbe_connection_status == 0"
        severity: "critical"
        
  ingestor_sbe_messages_total:
    description: "SBE messages processed"
    type: counter
    labels: ["message_type"]
    alerts:
      - name: "SBE Messages Stopped"
        condition: "rate(ingestor_sbe_messages_total[2m]) == 0"
        severity: "critical"

  # Performance
  ingestor_sbe_decode_duration_seconds:
    description: "SBE message decode time"
    type: histogram
    buckets: [0.00001, 0.00005, 0.0001, 0.0005, 0.001, 0.002]
    alerts:
      - name: "SBE Decode Slow"
        condition: "histogram_quantile(0.95, rate(ingestor_sbe_decode_duration_seconds_bucket[1m])) > 0.001"
        severity: "warning"
        
  ingestor_sbe_throughput_messages_per_second:
    description: "SBE message throughput"
    type: gauge
    alerts:
      - name: "SBE Throughput Low"
        condition: "ingestor_sbe_throughput_messages_per_second < 100"
        severity: "warning"

  # Gap Detection
  ingestor_sbe_sequence_gaps_total:
    description: "Detected sequence gaps"
    type: counter
    alerts:
      - name: "SBE Sequence Gaps"
        condition: "increase(ingestor_sbe_sequence_gaps_total[5m]) > 0"
        severity: "warning"
        
  ingestor_sbe_reconnections_total:
    description: "WebSocket reconnections"
    type: counter
    alerts:
      - name: "Frequent SBE Reconnections"
        condition: "rate(ingestor_sbe_reconnections_total[5m]) > 0.1"
        severity: "warning"
```

#### REST API Monitoring
```yaml
ingestor_rest_metrics:
  # API Health
  ingestor_rest_api_calls_total:
    description: "REST API calls made"
    type: counter
    labels: ["endpoint", "status"]
    
  ingestor_rest_api_duration_seconds:
    description: "REST API call duration"
    type: histogram
    buckets: [0.1, 0.2, 0.5, 1, 2, 5]
    alerts:
      - name: "REST API Slow"
        condition: "histogram_quantile(0.95, rate(ingestor_rest_api_duration_seconds_bucket[5m])) > 2"
        severity: "warning"
      - name: "REST API Errors"
        condition: "rate(ingestor_rest_api_calls_total{status=~'4..|5..'}[5m]) > 0.05"
        severity: "warning"

  # Rate Limiting
  ingestor_rest_rate_limit_remaining:
    description: "Remaining API rate limit"
    type: gauge
    alerts:
      - name: "API Rate Limit Low"
        condition: "ingestor_rest_rate_limit_remaining < 100"
        severity: "warning"
```

## Infrastructure Monitoring

### 1. Redis Cluster Health

#### Redis Performance Metrics
```yaml
redis_metrics:
  # Connection Health
  redis_connected_clients:
    description: "Number of connected clients"
    type: gauge
    alerts:
      - name: "Redis Connection Pool Exhausted"
        condition: "redis_connected_clients > 80"
        severity: "warning"
        
  redis_blocked_clients:
    description: "Clients blocked on operations"
    type: gauge
    alerts:
      - name: "Redis Clients Blocked"
        condition: "redis_blocked_clients > 5"
        severity: "warning"

  # Memory Usage
  redis_memory_used_bytes:
    description: "Redis memory usage"
    type: gauge
    alerts:
      - name: "Redis Memory High"
        condition: "redis_memory_used_bytes / redis_memory_max_bytes > 0.85"
        severity: "warning"
      - name: "Redis Memory Critical"
        condition: "redis_memory_used_bytes / redis_memory_max_bytes > 0.95"
        severity: "critical"

  # Performance
  redis_commands_processed_total:
    description: "Total commands processed"
    type: counter
    
  redis_commands_duration_seconds:
    description: "Command execution time"
    type: histogram
    buckets: [0.00001, 0.0001, 0.001, 0.01, 0.1]
    alerts:
      - name: "Redis Commands Slow"
        condition: "histogram_quantile(0.95, rate(redis_commands_duration_seconds_bucket[2m])) > 0.001"
        severity: "warning"

  # Hit Rate
  redis_keyspace_hits_total:
    description: "Cache hits"
    type: counter
    
  redis_keyspace_misses_total:
    description: "Cache misses"
    type: counter
    
  redis_hit_rate:
    description: "Cache hit rate"
    type: computed
    formula: "redis_keyspace_hits_total / (redis_keyspace_hits_total + redis_keyspace_misses_total)"
    alerts:
      - name: "Redis Hit Rate Low"
        condition: "redis_hit_rate < 0.95"
        severity: "warning"
```

### 2. AWS Infrastructure

#### Kinesis Data Streams
```yaml
kinesis_metrics:
  # Stream Health
  aws_kinesis_incoming_records:
    description: "Records ingested into stream"
    type: counter
    labels: ["stream_name"]
    
  aws_kinesis_incoming_bytes:
    description: "Bytes ingested into stream"
    type: counter
    labels: ["stream_name"]
    
  aws_kinesis_write_provisioned_throughput_exceeded:
    description: "Throttling events"
    type: counter
    alerts:
      - name: "Kinesis Throttling"
        condition: "rate(aws_kinesis_write_provisioned_throughput_exceeded[5m]) > 0"
        severity: "warning"

  # Processing Lag
  aws_kinesis_iterator_age_milliseconds:
    description: "Age of the latest record"
    type: gauge
    alerts:
      - name: "Kinesis Processing Lag"
        condition: "aws_kinesis_iterator_age_milliseconds > 30000"
        severity: "warning"
```

#### Lambda Functions
```yaml
lambda_metrics:
  aws_lambda_duration:
    description: "Function execution duration"
    type: histogram
    alerts:
      - name: "Lambda Duration High"
        condition: "aws_lambda_duration > 10000"  # >10s
        severity: "warning"
        
  aws_lambda_errors:
    description: "Function errors"
    type: counter
    alerts:
      - name: "Lambda Errors"
        condition: "rate(aws_lambda_errors[5m]) > 0.01"
        severity: "warning"
        
  aws_lambda_throttles:
    description: "Function throttles"
    type: counter
    alerts:
      - name: "Lambda Throttling"
        condition: "rate(aws_lambda_throttles[5m]) > 0"
        severity: "warning"
```

#### ECS/Fargate Services
```yaml
ecs_metrics:
  # Resource Utilization
  aws_ecs_cpu_utilization_percent:
    description: "CPU utilization percentage"
    type: gauge
    alerts:
      - name: "ECS CPU High"
        condition: "aws_ecs_cpu_utilization_percent > 80"
        severity: "warning"
        
  aws_ecs_memory_utilization_percent:
    description: "Memory utilization percentage"
    type: gauge
    alerts:
      - name: "ECS Memory High"
        condition: "aws_ecs_memory_utilization_percent > 85"
        severity: "warning"

  # Service Health
  aws_ecs_running_tasks_count:
    description: "Number of running tasks"
    type: gauge
    alerts:
      - name: "ECS Tasks Down"
        condition: "aws_ecs_running_tasks_count < aws_ecs_desired_tasks_count"
        severity: "critical"
```

## Business Metrics Monitoring

### 1. Prediction Accuracy

#### Model Performance Tracking
```yaml
business_metrics:
  # Accuracy Metrics
  model_directional_accuracy:
    description: "Percentage of correct direction predictions"
    type: histogram
    buckets: [0.45, 0.50, 0.55, 0.60, 0.65, 0.70]
    alerts:
      - name: "Model Accuracy Degraded"
        condition: "histogram_quantile(0.50, rate(model_directional_accuracy_bucket[1h])) < 0.55"
        severity: "warning"
        
  model_mean_absolute_error:
    description: "Average absolute prediction error"
    type: histogram
    buckets: [10, 25, 50, 100, 200, 500]
    alerts:
      - name: "Model Error High"
        condition: "histogram_quantile(0.50, rate(model_mean_absolute_error_bucket[1h])) > 100"
        severity: "warning"

  model_prediction_correlation:
    description: "Correlation between predicted and actual prices"
    type: histogram
    buckets: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7]
    alerts:
      - name: "Model Correlation Low"
        condition: "histogram_quantile(0.50, rate(model_prediction_correlation_bucket[1h])) < 0.3"
        severity: "warning"

  # Confidence Calibration
  model_confidence_calibration:
    description: "Confidence score vs actual accuracy alignment"
    type: histogram
    buckets: [0.7, 0.8, 0.85, 0.9, 0.95, 0.98]
```

### 2. Service Availability

#### SLA Monitoring
```yaml
availability_metrics:
  service_uptime_ratio:
    description: "Service availability percentage"
    type: gauge
    calculation: "successful_requests / total_requests"
    alerts:
      - name: "SLA Breach"
        condition: "service_uptime_ratio < 0.999"  # <99.9%
        severity: "critical"
        
  service_error_budget_remaining:
    description: "Remaining error budget for SLA"
    type: gauge
    calculation: "1 - ((total_errors / total_requests) / 0.001)"  # 0.1% error budget
    alerts:
      - name: "Error Budget Low"
        condition: "service_error_budget_remaining < 0.1"
        severity: "warning"
```

## Alert Management

### 1. Alert Routing

#### Severity-Based Routing
```yaml
alert_routing:
  critical:
    destinations:
      - pagerduty: "bitcoin-trading-team"
      - slack: "#bitcoin-alerts"
      - sms: "+1234567890"
    response_time: "5 minutes"
    escalation: "15 minutes"
    
  warning:
    destinations:
      - slack: "#bitcoin-monitoring"
      - email: "team@company.com"
    response_time: "30 minutes"
    escalation: "2 hours"
    
  info:
    destinations:
      - slack: "#bitcoin-logs"
    response_time: "N/A"
    escalation: "N/A"
```

#### Alert Grouping
```yaml
alert_grouping:
  inference_latency_alerts:
    group_by: ["service", "instance"]
    group_wait: "30s"
    group_interval: "5m"
    repeat_interval: "1h"
    
  redis_alerts:
    group_by: ["cluster", "node"]
    group_wait: "10s"
    group_interval: "2m"
    repeat_interval: "30m"
```

### 2. Runbooks and Response

#### Critical Alert Runbooks
```yaml
runbooks:
  inference_latency_high:
    title: "Inference Latency P99 >100ms"
    immediate_actions:
      - "Check Redis connectivity and latency"
      - "Verify model loading status"
      - "Check feature freshness and completeness"
      - "Review CPU/memory utilization"
    investigation:
      - "Analyze prediction latency breakdown"
      - "Check for Redis cluster issues"
      - "Review model performance metrics"
    escalation:
      - "If latency >200ms for >5min, consider service restart"
      - "If persistent, switch to fallback prediction mode"
      
  sbe_stream_disconnected:
    title: "SBE WebSocket Connection Lost"
    immediate_actions:
      - "Check network connectivity to Binance"
      - "Verify API credentials and permissions"
      - "Monitor automatic reconnection attempts"
    investigation:
      - "Review connection logs for error details"
      - "Check if Binance SBE service is operational"
      - "Analyze sequence gap impact"
    escalation:
      - "If reconnection fails >3 times, trigger REST re-anchor"
      - "If >30s downtime, escalate to senior engineer"
```

## Dashboard Configuration

### 1. Executive Dashboard

#### Key Performance Indicators
```yaml
executive_dashboard:
  layout: "grid_3x2"
  refresh_interval: "30s"
  
  panels:
    system_health:
      type: "singlestat"
      metric: "overall_system_health_score"
      thresholds: [0.8, 0.95]
      colors: ["red", "yellow", "green"]
      
    prediction_accuracy:
      type: "graph"
      metrics:
        - "model_directional_accuracy"
        - "model_mean_absolute_error"
      time_range: "24h"
      
    service_availability:
      type: "singlestat"
      metric: "service_uptime_ratio"
      format: "percent"
      decimals: 2
      
    active_alerts:
      type: "table"
      query: "ALERTS{alertstate='firing'}"
      columns: ["alertname", "severity", "service"]
      
    inference_latency:
      type: "graph"
      metrics:
        - "histogram_quantile(0.50, rate(inference_total_latency_seconds_bucket[1m]))"
        - "histogram_quantile(0.95, rate(inference_total_latency_seconds_bucket[1m]))"
        - "histogram_quantile(0.99, rate(inference_total_latency_seconds_bucket[1m]))"
      time_range: "1h"
      
    cost_tracking:
      type: "singlestat"
      metric: "aws_billing_estimated_charges"
      unit: "USD"
```

### 2. Technical Dashboard

#### Detailed Service Metrics
```yaml
technical_dashboard:
  layout: "grid_4x3"
  refresh_interval: "10s"
  
  panels:
    inference_service:
      type: "row"
      panels:
        - prediction_frequency
        - feature_freshness
        - model_performance
        - redis_operations
        
    aggregator_service:
      type: "row"
      panels:
        - kinesis_processing
        - feature_computation
        - redis_state_management
        - reanchor_operations
        
    ingestor_service:
      type: "row"
      panels:
        - sbe_stream_health
        - rest_api_performance
        - data_quality
        - gap_detection
        
    infrastructure:
      type: "row"
      panels:
        - redis_cluster_health
        - ecs_resource_usage
        - aws_service_health
        - network_performance
```

## Monitoring Tools and Implementation

### 1. Prometheus Configuration

#### Scrape Configuration
```yaml
prometheus_config:
  global:
    scrape_interval: 15s
    evaluation_interval: 15s
    
  scrape_configs:
    - job_name: 'inference-service'
      static_configs:
        - targets: ['inference-service:9092']
      scrape_interval: 5s  # More frequent for hot path
      
    - job_name: 'aggregator-service'
      static_configs:
        - targets: ['aggregator-service:9091']
      scrape_interval: 10s
      
    - job_name: 'ingestor-sbe-service'
      static_configs:
        - targets: ['ingestor-sbe-service:9090']
      scrape_interval: 10s
      
    - job_name: 'redis-exporter'
      static_configs:
        - targets: ['redis-exporter:9121']
      scrape_interval: 15s
      
    - job_name: 'aws-cloudwatch'
      ec2_sd_configs:
        - region: 'us-east-1'
          port: 9100
      relabel_configs:
        - source_labels: [__meta_ec2_tag_Service]
          target_label: service
```

### 2. Grafana Dashboards

#### Dashboard Templates
```json
{
  "bitcoin_pipeline_overview": {
    "title": "Bitcoin Pipeline Overview",
    "tags": ["bitcoin", "trading", "overview"],
    "templating": {
      "list": [
        {
          "name": "service",
          "type": "query",
          "query": "label_values(up, job)"
        },
        {
          "name": "time_range",
          "type": "interval",
          "options": ["5m", "15m", "1h", "6h", "24h"]
        }
      ]
    }
  }
}
```

### 3. Alert Manager Configuration

#### Alert Routing Rules
```yaml
alertmanager_config:
  global:
    slack_api_url: 'https://hooks.slack.com/services/XXX'
    
  route:
    group_by: ['alertname', 'service']
    group_wait: 10s
    group_interval: 10s
    repeat_interval: 1h
    receiver: 'web.hook'
    routes:
      - match:
          severity: critical
        receiver: 'pagerduty'
        group_wait: 10s
        repeat_interval: 5m
        
      - match:
          severity: warning
        receiver: 'slack'
        group_wait: 30s
        repeat_interval: 30m
        
  receivers:
    - name: 'pagerduty'
      pagerduty_configs:
        - service_key: 'YOUR_PAGERDUTY_KEY'
          description: 'Bitcoin Pipeline Alert: {{ .GroupLabels.alertname }}'
          
    - name: 'slack'
      slack_configs:
        - channel: '#bitcoin-alerts'
          title: 'Bitcoin Pipeline Alert'
          text: '{{ range .Alerts }}{{ .Annotations.summary }}{{ end }}'
```

This comprehensive monitoring strategy ensures the Bitcoin prediction pipeline maintains sub-100ms inference latency, 99.9% availability, and accurate 10-second ahead predictions through proactive observability and rapid incident response.