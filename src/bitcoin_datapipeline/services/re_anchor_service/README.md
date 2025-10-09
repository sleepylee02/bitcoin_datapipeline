# Re-anchor Service

## Service Overview
**Purpose:** Atomic Redis recovery operations for zero-downtime gap recovery  
**Deployment:** Single Docker container / AWS ECS service  
**Ports:** 8084 (health endpoint)

## Responsibilities
- Coordinate atomic re-anchoring operations
- Manage temporary Redis keys during recovery
- Ensure zero-downtime key swapping
- Validate data consistency during transitions

## Architecture Position
```
Gap Detector → [Re-anchor Service] → Redis (atomic swap)
REST Ingestor → [Re-anchor Service] → Redis (temp keys)
```

## Key Components

### 1. Atomic Operations Manager
- Redis MULTI/EXEC transactions for atomic swaps
- Temporary key management (`*.new.*` pattern)
- Rollback mechanisms for failed operations

### 2. Recovery Coordinator
- Orchestrate multi-step recovery process
- Validate data integrity before swapping
- Coordinate with multiple data sources

### 3. Zero-downtime Guarantees
- Never clear live keys during recovery
- Use atomic RENAME operations
- Maintain service availability throughout process

## Redis Key Patterns

### During Recovery
```redis
# Temporary keys
ob:new:BTCUSDT              # New order book state
tr:new:BTCUSDT:1s           # New 1s trade stats
tr:new:BTCUSDT:5s           # New 5s trade stats
feat:new:BTCUSDT            # New feature vector

# Control flag
reanchor:BTCUSDT            # Recovery in progress flag
```

### Atomic Swap Process
```redis
# All operations succeed or all fail
RENAME ob:new:BTCUSDT → ob:BTCUSDT
RENAME tr:new:BTCUSDT:1s → tr:BTCUSDT:1s
RENAME tr:new:BTCUSDT:5s → tr:BTCUSDT:5s
RENAME feat:new:BTCUSDT → feat:BTCUSDT
DEL reanchor:BTCUSDT
```

## Configuration
```yaml
re_anchor:
  operation_timeout_seconds: 30
  max_retry_attempts: 3
  consistency_check_enabled: true
  
redis:
  cluster_mode: true
  operation_timeout_ms: 100
```

## TODO Implementation
1. Create Redis atomic operations manager
2. Implement temporary key lifecycle management
3. Add data consistency validation
4. Create recovery orchestration logic
5. Add monitoring and failure recovery
6. Implement rollback mechanisms