# Bitcoin Pipeline - Deployment Configuration

This directory contains Docker/production deployment configurations.

## Environment Strategy

### Development (Local)
- **Single `.env`** in project root
- All services read from the same environment file
- Simplified setup for development workflow

```bash
# Development usage
cp .env.example .env           # In project root
./scripts/setup-dev.sh         # Runs all services locally
```

### Production (Docker/K8s)
- **Service-specific `.env` files** in `deployment/env/`
- Each service gets only the variables it needs
- Better security and resource isolation

```bash
# Production usage
cp deployment/env/.env.example deployment/.env    # Docker compose variables
docker-compose up -d                              # Uses service-specific envs
```

## How It Works

### Development Flow
```
.env (root)
    ↓
All services read from this single file
    ↓
REST Ingestor ← BINANCE_API_KEY, REST_INGESTOR_LOG_LEVEL, etc.
SBE Ingestor  ← BINANCE_API_KEY, SBE_INGESTOR_LOG_LEVEL, etc.
Aggregator    ← REDIS_HOST, AGGREGATOR_BATCH_SIZE, etc.
```

### Production Flow
```
deployment/.env (Docker Compose variables)
    ↓
docker-compose.yml substitutes ${VARIABLES}
    ↓
.env.rest-ingestor   → REST Ingestor container
.env.sbe-ingestor    → SBE Ingestor container  
.env.aggregator      → Aggregator container
.env.data-connector  → Data Connector container
```

## Service Configuration Loading

Each service should load config in this priority order:

1. **Environment variables** (highest priority)
2. **Service-specific .env file** (Docker)
3. **Default values** (lowest priority)

Example in service code:
```python
import os
from dataclasses import dataclass

@dataclass
class RestIngestorConfig:
    # Will read from env vars or use defaults
    log_level: str = os.getenv('REST_INGESTOR_LOG_LEVEL', 'INFO')
    rate_limit: int = int(os.getenv('REST_INGESTOR_RATE_LIMIT', '1200'))
    binance_api_key: str = os.getenv('BINANCE_API_KEY')  # Required
```

## Files Structure

```
deployment/
├── .env.example                 # Template for Docker variables
├── .env                        # Your Docker variables (create from template)
├── docker-compose.yml          # Uses deployment/.env for substitution
├── docker-compose.dev.yml      # Development override
└── env/
    ├── .env.example            # Template for all service envs
    ├── .env.rest-ingestor      # Production REST service vars
    ├── .env.sbe-ingestor       # Production SBE service vars
    ├── .env.aggregator         # Production Aggregator vars
    └── .env.data-connector     # Production Data Connector vars
```

## Quick Setup

### Development
```bash
# Project root
cp .env.example .env
# Edit .env with your values
./scripts/setup-dev.sh
```

### Docker Production
```bash
# Deployment directory
cp env/.env.example .env
# Edit .env with production values
docker-compose up -d
```

### Kubernetes
```bash
# Use env/ files to create ConfigMaps/Secrets
kubectl create configmap rest-ingestor-config --from-env-file=env/.env.rest-ingestor
```