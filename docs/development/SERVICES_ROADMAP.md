# Services Implementation Roadmap

## Current Status & Next Steps

### ✅ Already Implemented
```
services/
├── sbe-ingestor/          ✅ SBE WebSocket → Kinesis
├── rest-ingestor/         ✅ REST API → S3 (historical data)
├── aggregator/            ✅ Kinesis → Redis (hot state management)
└── data-connector/        ✅ S3 → RDBMS (MLOps feature store)
```

### 🚧 Need Implementation
```
services/
├── gap-detector/          🔲 Monitor SBE sequence gaps
├── re-anchor-service/     🔲 Atomic Redis key swapping
├── inference/             🔲 Redis → 10s price predictions
└── trainer/               🔲 RDBMS → model training
```

## Data Flow Architecture

### Current Working Flow
```
SBE Stream → Kinesis → Aggregator → Redis Hot State
REST API → S3 Bronze Layer → Data Connector → RDBMS Feature Store
```

### Target Complete Flow  
```
Hot Path:     SBE Stream → Kinesis → Aggregator → Redis → Inference (every 2s)
Reliability:  Gap Detector → Re-anchor Service → Redis (atomic swap)
              REST API → Recovery Data → Redis Hot State
MLOps:        S3 Bronze/Silver → Data Connector → RDBMS → Trainer → Models
```

## Implementation Priority

### Phase 1: Solidify Data Ingestion (CURRENT)
- [x] SBE ingestor: WebSocket → Kinesis ✅
- [x] REST ingestor: API → S3 ✅  
- [x] Aggregator: Kinesis → Redis ✅
- [x] Data Connector: S3 → RDBMS MLOps hub ✅
- [ ] **Test end-to-end data flow**
- [ ] **Verify Redis schema implementation**
- [ ] **Validate RDBMS feature store**

### Phase 2: Add Reliability Layer
- [ ] Gap Detector: Monitor SBE sequences
- [ ] Re-anchor Service: Atomic Redis operations
- [ ] Update REST ingestor: Add gap recovery mode

### Phase 3: Add ML Training Pipeline
- [ ] Trainer Service: RDBMS → model training
- [ ] Feature engineering SQL pipelines
- [ ] Experiment tracking and model registry
- [ ] Model artifact management (S3 integration)

### Phase 4: Add Inference Layer  
- [ ] Inference Service: Redis → 10s predictions
- [ ] Model deployment from registry
- [ ] Performance optimization (<100ms latency)
- [ ] Prediction accuracy monitoring

## Service Responsibilities

### Aggregator Service (EXISTS)
**Purpose:** Transform Kinesis events → Redis hot state
**Status:** ✅ Fully implemented
**Key Features:**
- Kinesis stream consumption
- Redis schema management (`ob:`, `tr:`, `feat:` keys)
- Atomic re-anchoring support
- Feature computation (every 2s)

### Data Connector Service (EXISTS)
**Purpose:** S3 ETL → RDBMS feature store for MLOps
**Status:** ✅ Fully implemented  
**Key Features:**
- S3 bronze/silver data processing
- PostgreSQL feature store management
- ML experiment tracking tables
- Model registry and deployment tracking

### Gap Detector Service (TODO)
**Purpose:** Monitor SBE sequence integrity
**Status:** 🔲 Need to implement
**Key Features:**
- Sequence number tracking
- Gap detection algorithms  
- Recovery trigger coordination

### Re-anchor Service (TODO)
**Purpose:** Zero-downtime Redis recovery
**Status:** 🔲 Need to implement
**Key Features:**
- Atomic key swapping
- Temporary key management
- Recovery coordination

## Configuration Strategy

### Current Config Locations
```
services/sbe-ingestor/config/local.yaml     ✅ Kinesis configuration
services/rest-ingestor/config/local.yaml   ✅ S3 configuration  
services/aggregator/config/local.yaml      ✅ Redis configuration
```

### Missing Configurations
- Redis connection settings in ingestors
- Gap detection parameters
- Re-anchor operation timeouts
- Inference service parameters

## Next Immediate Actions

1. **Test Current Flow** - Verify SBE → Kinesis → Redis pipeline works
2. **Check Redis Schema** - Ensure aggregator implements documented schema
3. **Add Missing Services** - Implement gap-detector and re-anchor-service
4. **Integration Testing** - End-to-end data flow validation

## Development Guidelines

- **Single Responsibility** - Each service handles one specific function
- **Configuration Driven** - All parameters externalized in YAML configs
- **Error Isolation** - Service failures don't cascade to others
- **Observable** - All services expose health and metrics endpoints
- **Atomic Operations** - Redis updates use transactions for consistency