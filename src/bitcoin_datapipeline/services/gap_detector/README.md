# Gap Detector Service

## Service Overview
**Purpose:** Real-time SBE sequence monitoring and gap detection for Bitcoin pipeline reliability  
**Deployment:** Single Docker container / AWS Lambda function  
**Ports:** 8082 (health endpoint)

## Responsibilities
- Monitor sequence numbers from SBE stream events
- Detect gaps in data sequence  
- Trigger atomic re-anchoring when gaps detected
- Coordinate with REST ingestor for gap recovery

## Architecture Position
```
SBE → Kinesis → [Gap Detector] → Re-anchor Service
                      ↓
                REST Ingestor (trigger recovery)
```

## Key Components

### 1. Sequence Monitor
- Tracks sequence numbers from SBE events
- Maintains expected sequence state
- Detects missing sequences or out-of-order messages

### 2. Gap Detection Logic
- Configurable gap tolerance (e.g., missing 5+ consecutive sequences)
- Time-based detection (no data for X seconds)
- False positive prevention

### 3. Recovery Trigger
- Sets `reanchor:BTCUSDT` flag in Redis
- Triggers REST ingestor recovery mode
- Coordinates with re-anchor service

## Configuration
```yaml
gap_detection:
  sequence_timeout_seconds: 30
  max_sequence_gap: 5
  recovery_cooldown_minutes: 5
  
monitoring:
  check_interval_seconds: 1
  metrics_port: 8082
```

## TODO Implementation
1. Create Kinesis consumer for sequence monitoring
2. Implement gap detection algorithms
3. Add Redis integration for flag management
4. Create recovery coordination logic
5. Add comprehensive monitoring and alerting