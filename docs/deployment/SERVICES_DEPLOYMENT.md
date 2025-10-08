# Bitcoin Data Pipeline - Service Deployment Guide

## Docker & AWS Service Model

Each service directory represents **one deployable component** that runs as:
- **Local Development:** Docker container
- **AWS Production:** ECS service or Lambda function

## Service Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      BITCOIN DATA PIPELINE SERVICES                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │  sbe-ingestor   │  │ rest-ingestor   │  │  aggregator     │        │
│  │  Port: 8081     │  │ Port: 8080      │  │ Port: 8082      │        │
│  │  (ECS Service)  │  │ (ECS Service)   │  │ (ECS Service)   │        │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘        │
│           │                    │                    │                  │
│           ▼                    ▼                    ▼                  │
│    [Kinesis Streams]    [S3 Bronze Layer]    [Redis Hot State]        │
│           │                    │                    │                  │
│           └────────────────────┼────────────────────┘                  │
│                                │                                        │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐        │
│  │ gap-detector    │  │re-anchor-service│  │ data-connector  │        │
│  │ Port: 8082      │  │ Port: 8084      │  │ Port: 8083      │        │
│  │ (Lambda/ECS)    │  │ (ECS Service)   │  │ (ECS Service)   │        │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘        │
│           │                    │                    │                  │
│           ▼                    ▼                    ▼                  │
│    [Gap Detection]      [Atomic Recovery]    [S3 → Database]          │
│                                                                         │
│  ┌─────────────────┐  ┌─────────────────┐                            │
│  │   inference     │  │    trainer      │                            │
│  │   Port: 8085    │  │   Port: 8086    │                            │
│  │  (ECS Service)  │  │  (Batch Job)    │                            │
│  └─────────────────┘  └─────────────────┘                            │
│           │                    │                                        │
│           ▼                    ▼                                        │
│    [10s Predictions]    [Model Training]                              │
└─────────────────────────────────────────────────────────────────────────┘
```

## Service Deployment Matrix

| Service | Local Port | AWS Service | CPU | Memory | Purpose |
|---------|------------|-------------|-----|--------|---------|
| **sbe-ingestor** | 8081 | ECS Service | 1.0 | 2GB | SBE → Kinesis real-time streaming |
| **rest-ingestor** | 8080 | ECS Service | 0.5 | 1GB | REST → S3 historical collection |
| **aggregator** | 8082 | ECS Service | 1.5 | 3GB | Kinesis → Redis hot state |
| **gap-detector** | 8082 | Lambda/ECS | 0.5 | 1GB | Sequence monitoring |
| **re-anchor-service** | 8084 | ECS Service | 1.0 | 2GB | Atomic Redis recovery |
| **data-connector** | 8083 | ECS Service | 2.0 | 4GB | S3 ETL → Database |
| **inference** | 8085 | ECS Service | 2.0 | 4GB | Redis → 10s predictions |
| **trainer** | 8086 | Batch Job | 4.0 | 8GB | Model training pipeline |

## Docker Development Workflow

### 1. Individual Service Development
```bash
# Navigate to service directory
cd services/sbe-ingestor/

# Build container
docker build -t bitcoin-sbe-ingestor .

# Run with local config
docker run -d --name sbe-ingestor \
  -p 8081:8081 \
  -e CONFIG_FILE=config/local.yaml \
  bitcoin-sbe-ingestor

# Check health
curl http://localhost:8081/health
```

### 2. Multi-Service Local Environment
```bash
# Start infrastructure
docker-compose up -d localstack redis postgres

# Start core services
docker-compose up -d sbe-ingestor rest-ingestor aggregator

# Start reliability services  
docker-compose up -d gap-detector re-anchor-service

# Start analytics services
docker-compose up -d data-connector inference
```

### 3. Service Dependencies
```yaml
# docker-compose.yml service dependencies
version: '3.8'
services:
  sbe-ingestor:
    depends_on: [localstack]
    ports: ["8081:8081"]
    
  rest-ingestor:
    depends_on: [localstack]
    ports: ["8080:8080"]
    
  aggregator:
    depends_on: [localstack, redis, sbe-ingestor]
    ports: ["8082:8082"]
    
  gap-detector:
    depends_on: [localstack, aggregator]
    ports: ["8082:8082"]
    
  re-anchor-service:
    depends_on: [redis, gap-detector]
    ports: ["8084:8084"]
    
  data-connector:
    depends_on: [localstack, postgres]
    ports: ["8083:8083"]
    
  inference:
    depends_on: [redis, aggregator]
    ports: ["8085:8085"]
```

## AWS Production Deployment

### ECS Cluster Configuration
```yaml
Cluster: bitcoin-pipeline-cluster
Services:
  - sbe-ingestor:
      desired_count: 2          # High availability
      deployment_type: rolling
      auto_scaling: enabled
      
  - rest-ingestor:
      desired_count: 1          # Single instance sufficient
      deployment_type: rolling
      scheduled_scaling: true   # Scale up during market hours
      
  - aggregator:
      desired_count: 2          # Critical hot path
      deployment_type: blue_green
      auto_scaling: enabled
      priority: high
      
  - re-anchor-service:
      desired_count: 1          # Singleton pattern
      deployment_type: rolling
      
  - data-connector:
      desired_count: 1          # Batch processing
      scheduled_scaling: true   # Scale for heavy ETL
      
  - inference:
      desired_count: 3          # High throughput
      deployment_type: blue_green
      auto_scaling: enabled
      priority: high
```

### Service-Specific AWS Configurations

#### SBE Ingestor (High Performance)
```yaml
aws_config:
  service_type: ECS
  task_definition:
    cpu: 1024          # 1 vCPU
    memory: 2048       # 2GB
    network_mode: awsvpc
    placement_constraints:
      - type: memberOf
        expression: "attribute:instance-type =~ t3.*"
  auto_scaling:
    min_capacity: 1
    max_capacity: 4
    target_cpu: 70
```

#### Gap Detector (Event-Driven)
```yaml
aws_config:
  service_type: Lambda    # Alternative: ECS for continuous monitoring
  runtime: python3.12
  timeout: 300           # 5 minutes
  memory: 1024          # 1GB
  triggers:
    - kinesis_stream: market-sbe-trade
    - schedule: rate(1 minute)  # Periodic health checks
```

#### Aggregator (Mission Critical)
```yaml
aws_config:
  service_type: ECS
  task_definition:
    cpu: 1536          # 1.5 vCPU  
    memory: 3072       # 3GB
    essential: true    # Never stop this service
  auto_scaling:
    min_capacity: 2    # Always have 2 instances
    max_capacity: 6
    target_cpu: 60     # Conservative scaling
  placement_strategy:
    - type: spread
      field: "attribute:ecs.availability-zone"
```

## Health Check Strategy

### Service Health Endpoints
```bash
# All services expose standardized health endpoints
GET /health

# Expected response format:
{
  "status": "healthy|degraded|unhealthy",
  "service": "<service-name>",
  "timestamp": "2024-01-15T14:30:00Z",
  "components": {
    "component1": {"status": "healthy", ...},
    "component2": {"status": "degraded", ...}
  }
}
```

### AWS Health Check Configuration
```yaml
health_checks:
  sbe_ingestor:
    path: "/health"
    port: 8081
    protocol: HTTP
    interval: 30s
    timeout: 5s
    healthy_threshold: 3
    unhealthy_threshold: 2
    
  aggregator:
    path: "/health"
    port: 8082
    protocol: HTTP
    interval: 15s      # More frequent for critical service
    timeout: 3s
    healthy_threshold: 2
    unhealthy_threshold: 1
```

## Service Communication

### Internal Network Architecture
```
Production VPC:
├── Private Subnet A (Services)
│   ├── sbe-ingestor:8081
│   ├── aggregator:8082  
│   ├── re-anchor-service:8084
│   └── inference:8085
├── Private Subnet B (Data)
│   ├── Redis Cluster:6379
│   ├── RDS Aurora:5432
│   └── data-connector:8083
└── Public Subnet (Gateway)
    └── ALB → Service Discovery
```

### Service Discovery
```yaml
# AWS Service Discovery configuration
namespace: bitcoin-pipeline.local
services:
  - name: sbe-ingestor
    dns_name: sbe-ingestor.bitcoin-pipeline.local
    port: 8081
    
  - name: aggregator
    dns_name: aggregator.bitcoin-pipeline.local
    port: 8082
    
  - name: redis-cluster
    dns_name: redis.bitcoin-pipeline.local
    port: 6379
```

## Deployment Pipelines

### CI/CD Strategy
```yaml
GitHub Actions Pipeline:
1. Code Push → Branch
2. Unit Tests (per service)
3. Integration Tests (service pairs)
4. Docker Build (parallel)
5. Security Scan
6. Deploy to Staging ECS
7. E2E Tests
8. Deploy to Production ECS (blue/green)
9. Monitor & Rollback capability
```

### Service-Specific Deploy Commands
```bash
# Deploy single service
./deploy.sh sbe-ingestor production

# Deploy with dependency chain
./deploy.sh aggregator production --wait-for sbe-ingestor

# Deploy reliability services together
./deploy.sh gap-detector,re-anchor-service production

# Full pipeline deployment
./deploy.sh all production --strategy blue-green
```

This deployment model ensures each service can be developed, tested, and deployed independently while maintaining the overall system reliability and performance requirements.