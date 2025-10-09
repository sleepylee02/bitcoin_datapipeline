# Bitcoin Pipeline - Test Directory

This directory contains all testing infrastructure for the Bitcoin Pipeline project using pytest.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+ 
- Virtual environment activated
- Development environment set up using root scripts

### Environment Setup
```bash
# From project root - use the automated setup script
./scripts/setup-dev.sh
```

**That's it!** The setup script handles:
- ✅ Virtual environment verification
- ✅ Installing dev dependencies (`requirements-dev.txt`)
- ✅ Installing all service dependencies
- ✅ Building SBE decoder (C++ extension)
- ✅ Installing project in development mode

### Environment Variables
Create `.env` file in **project root**:

```bash
# Required for API tests
BINANCE_API_KEY=your_test_api_key
BINANCE_API_SECRET=your_test_api_secret

# Required for E2E tests (LocalStack)
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=us-east-1

# Test configuration
TEST_DURATION=30
LOG_LEVEL=DEBUG
ENVIRONMENT=test
```

### Run Tests Immediately
```bash
# Quick verification (unit tests only)
pytest -m unit

# All tests
pytest

# With coverage
pytest --cov=src --cov-report=term-missing
```

## 📁 Directory Structure

```
tests/
├── README.md                    # This file
├── configs/                     # Test configurations
│   ├── rest-local.yaml         # REST ingestor local test config
│   └── sbe-local.yaml          # SBE ingestor local test config
├── data/                       # Test data storage (auto-created)
│   ├── checkpoints/            # Test checkpoints
│   ├── logs/                   # Test logs
│   └── output/                 # Test output files
├── fixtures/                   # Test fixtures and mock data
├── unit/                       # Unit tests
│   ├── test_rest_client.py     # Direct REST client test
│   └── test_sbe_client.py      # Direct SBE client test
├── integration/                # Integration tests
│   └── test_full_services.py   # Full service integration test
├── e2e/                        # End-to-end tests
│   └── test_pipeline.py        # Complete pipeline test
└── docker-compose.test.yml     # Docker test environment
```

## 🏃 Running Tests

### By Test Type
```bash
# Unit tests only (fast, no dependencies)
pytest -m unit

# Integration tests (local dependencies)
pytest -m integration

# End-to-end tests (Docker environment required)
pytest -m e2e

# Exclude slow tests
pytest -m "not slow"

# API tests only
pytest -m api
```

### By Specific Files
```bash
# Single test file
pytest tests/unit/test_rest_client.py

# Multiple files
pytest tests/unit/ tests/integration/

# Specific test function
pytest tests/unit/test_rest_client.py::test_connection
```

### With Coverage and Output Options
```bash
# Basic coverage
pytest --cov=src

# Coverage with missing lines report
pytest --cov=src --cov-report=term-missing

# Generate HTML coverage report
pytest --cov=src --cov-report=html

# Verbose output with traceback
pytest -v --tb=short

# Stop on first failure
pytest -x

# Run tests in parallel (requires pytest-xdist)
pytest -n auto
```

## 🐳 E2E Tests with LocalStack

E2E tests require LocalStack to simulate AWS services.

### 1. Start LocalStack
```bash
# Option 1: Direct Docker
docker run -d -p 4566:4566 localstack/localstack

# Option 2: Using project's docker-compose
docker-compose -f tests/docker-compose.test.yml up -d
```

### 2. Setup AWS Resources
```bash
# From project root - creates Kinesis streams, S3 buckets
./scripts/setup-localstack.sh
```

### 3. Run E2E Tests
```bash
# Run E2E tests only
pytest -m e2e

# Run with detailed output
pytest -m e2e -v -s

# Clean up after tests
docker-compose -f tests/docker-compose.test.yml down
```

## 🏷️ Test Categories & Markers

Tests are organized by markers defined in `pyproject.toml`:

### `@pytest.mark.unit`
- Test individual components in isolation
- No external dependencies required
- Fast execution (< 30 seconds each)
- Run with: `pytest -m unit`

### `@pytest.mark.integration`
- Test services with minimal dependencies
- May require local file system or mock services
- Medium execution time (1-5 minutes each)
- Run with: `pytest -m integration`

### `@pytest.mark.e2e`
- Test complete data pipeline
- Requires full Docker environment with LocalStack
- Longer execution time (5-15 minutes)
- Run with: `pytest -m e2e`

### `@pytest.mark.slow`
- Tests that take >5 seconds to run
- Can be excluded with: `pytest -m "not slow"`

### `@pytest.mark.api`
- Tests requiring external API access (Binance)
- Run with: `pytest -m api`

## ⚙️ Configuration

### Test Configuration Files
- `configs/rest-local.yaml` - REST ingestor local test config
- `configs/sbe-local.yaml` - SBE ingestor local test config

### Pytest Configuration
Configured in `pyproject.toml` with settings for:
- Test discovery patterns
- Output formatting
- Async test support
- Custom markers
- Coverage reporting

## 🔧 Troubleshooting

### Common Issues

**Import Errors**:
```bash
# Re-run the development setup script
./scripts/setup-dev.sh

# Or verify you're in the project root
cd /path/to/bitcoin_datapipeline
pytest
```

**No Tests Found**:
```bash
# Check pytest discovers tests correctly
pytest --collect-only

# Ensure test files match patterns in pyproject.toml
# test_*.py, *_test.py
```

**SBE Decoder Issues**:
```bash
# Build the SBE decoder
cd src/bitcoin_datapipeline/services/sbe_ingestor/sbe_decoder
python setup.py build_ext --inplace
```

**LocalStack Connection Issues**:
```bash
# Check LocalStack is running
curl http://localhost:4566/health

# Recreate resources
./scripts/setup-localstack.sh

# Reset LocalStack
docker-compose -f tests/docker-compose.test.yml down
docker-compose -f tests/docker-compose.test.yml up -d
```

**Virtual Environment Issues**:
```bash
# Recreate virtual environment and setup
deactivate
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate
./scripts/setup-dev.sh
```

## 🚀 Best Practices

1. **Use markers**: Tag tests with appropriate markers (`@pytest.mark.unit`, etc.)
2. **Run fast tests first**: `pytest -m "unit or integration" && pytest -m e2e`
3. **Clean environment**: Delete `tests/data/` between major test runs
4. **Isolated testing**: Each test should be independent
5. **Resource cleanup**: Tests should clean up after themselves
6. **Deterministic**: Tests should produce consistent results

## 🔄 Development Workflow

```bash
# Quick development cycle
pytest -m unit -x --tb=short  # Stop on first failure

# Before committing
pytest -m "unit or integration"

# Full test suite (CI simulation)
pytest --cov=src --cov-report=term-missing

# Debug specific test
pytest tests/unit/test_rest_client.py::test_connection -v -s --pdb
```

## 📊 Data Management

### Test Data (`data/`)
- Automatically created during tests
- Safe to delete between test runs
- Gitignored to avoid committing test artifacts

### Logs (`data/logs/`)
- Service logs from test runs
- Useful for debugging test failures
- Automatically rotated