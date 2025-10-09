# Bitcoin Data Pipeline

[![Tests](https://github.com/bitcoin-pipeline/bitcoin-datapipeline/workflows/Tests/badge.svg)](https://github.com/bitcoin-pipeline/bitcoin-datapipeline/actions)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Real-time Bitcoin price prediction service** that predicts Bitcoin price **10 seconds ahead** with predictions generated **every 2 seconds**. The system uses a hot-path architecture with atomic re-anchoring for zero-downtime reliability, achieving sub-100ms inference latency.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Virtual environment recommended

### Development Setup
```bash
# Clone and setup
git clone <repository-url>
cd bitcoin-datapipeline

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install development dependencies and build
./scripts/setup-dev.sh
```

### Run Tests
```bash
# Run all tests
pytest

# Run specific tests
pytest tests/unit/test_rest_client.py -v
pytest tests/integration/ -v
```

## 🏗️ Architecture Overview

### Tri-Layer Architecture
1. **Hot Path (Real-time)**: SBE WebSocket → Kinesis → Redis → Inference (every 2s)
2. **Reliability Path**: REST API → Gap Detection → Atomic Re-anchor → S3 Backfill  
3. **Training Pipeline**: S3 → RDBMS → Model Training → Deployment

### Key Features
- ⚡ **Sub-100ms inference latency** (P99)
- 🔄 **Zero-downtime operation** with atomic re-anchoring
- 📊 **10-second ahead predictions** every 2 seconds
- 🛡️ **99.9% uptime** with graceful degradation
- 🔗 **Microservice architecture** with independent deployment

## 📁 Project Structure

```
bitcoin-datapipeline/
├── src/bitcoin_datapipeline/    # Main source code
│   ├── services/                # Microservices
│   │   ├── sbe-ingestor/       # Real-time SBE WebSocket client
│   │   ├── rest-ingestor/      # Historical data collection  
│   │   ├── aggregator/         # Real-time data aggregation
│   │   ├── data-connector/     # S3 to RDBMS pipeline
│   │   ├── inference/          # Price prediction service
│   │   └── trainer/            # Model training pipeline
│   ├── schemas/                # Data schemas (Avro)
│   └── schemas/                # Data schemas (Avro)
├── tests/                      # Test suite
├── docs/                       # Documentation
├── deployment/                 # Infrastructure as code
└── scripts/                    # Automation scripts
```

## 🎯 Core Services

| Service | Purpose | Technology Stack |
|---------|---------|------------------|
| **sbe-ingestor** | Real-time market data | SBE WebSocket, C++ decoder, Kinesis |
| **rest-ingestor** | Historical backfill | REST API, S3, checkpointing |
| **aggregator** | Feature engineering | Redis, rolling windows, atomic ops |
| **inference** | Price prediction | MLP model, Redis, <100ms latency |
| **data-connector** | Training pipeline | S3, PostgreSQL, feature store |

## 📊 Performance Targets

- **Prediction frequency**: Every 2 seconds
- **Prediction horizon**: 10 seconds ahead
- **Inference latency**: <100ms (P99)
- **Feature freshness**: <2s for optimal predictions
- **Service availability**: 99.9% uptime

## 🛠️ Development

### Local Testing
```bash
# Run individual service tests
pytest tests/unit/test_rest_client.py
pytest tests/unit/test_sbe_client.py

# Run integration tests
pytest tests/integration/ -v

# Run with Docker (E2E tests)
cd tests && docker-compose -f docker-compose.test.yml up -d
```

### Development Scripts
The `scripts/` directory contains automation scripts for development workflow:

#### `scripts/setup-dev.sh`
**Complete development environment setup** - handles all dependencies and builds.

```bash
# From project root
./scripts/setup-dev.sh
```

**What it does:**
- ✅ Checks for virtual environment
- ✅ Upgrades pip and installs dev dependencies  
- ✅ Installs all service dependencies from `requirements.txt` files
- ✅ Builds SBE decoder (C++ extension)
- ✅ Installs project in development mode (`pip install -e .`)
- ✅ Verifies imports and shows next steps

**Requirements:**
- Virtual environment activated
- `pyproject.toml` and `requirements-dev.txt` present
- SBE decoder build dependencies

#### `scripts/setup-localstack.sh`
**LocalStack AWS resource setup** - creates AWS resources for E2E testing.

```bash
# Start LocalStack first
docker run -d -p 4566:4566 localstack/localstack

# Setup AWS resources
./scripts/setup-localstack.sh
```

**What it does:**
- ✅ Waits for LocalStack to be ready (60s timeout)
- ✅ Creates Kinesis streams for market data
- ✅ Creates S3 buckets for data storage
- ✅ Lists created resources for verification

**Requirements:**
- LocalStack running on port 4566
- AWS CLI installed
- Docker for LocalStack container

**Troubleshooting:**
```bash
# Check LocalStack health
curl http://localhost:4566/health

# Manual resource creation
aws --endpoint-url=http://localhost:4566 kinesis list-streams --region us-east-1
```

### Service Development
Each service maintains its own:
- `requirements.txt` for production dependencies
- `Dockerfile` for containerization
- `config/` for environment-specific settings
- `README.md` for service-specific documentation

### Code Quality
```bash
# Format code
black .
isort .

# Type checking
mypy src/

# Linting
flake8 src/
```

## 🚀 Deployment

### Docker (Development)
```bash
# Build and run individual services
cd src/bitcoin_datapipeline/services/rest-ingestor
docker build -t rest-ingestor .
docker run rest-ingestor
```

### AWS (Production)
See [deployment documentation](docs/deployment/) for:
- Terraform infrastructure setup
- ECS/Fargate service deployment
- Monitoring and alerting configuration

## 📚 Documentation

- **[Architecture](docs/architecture/)** - System design and data flow
- **[Deployment](docs/deployment/)** - Infrastructure and deployment guides  
- **[Schemas](docs/schemas/)** - Data models and formats
- **[Operations](docs/operations/)** - Monitoring, testing, and maintenance
- **[Development](docs/development/)** - Contributing and roadmap

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🆘 Support

- **Documentation**: [docs/](docs/)
- **Issues**: [GitHub Issues](https://github.com/bitcoin-pipeline/bitcoin-datapipeline/issues)
- **Discussions**: [GitHub Discussions](https://github.com/bitcoin-pipeline/bitcoin-datapipeline/discussions)
