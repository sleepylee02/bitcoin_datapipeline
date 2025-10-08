# Bitcoin Pipeline - Test Directory

This directory contains all testing infrastructure and scripts for the Bitcoin Pipeline project.

## Directory Structure

```
test/
├── README.md                    # This file
├── configs/                     # Test configurations
│   ├── rest-local.yaml         # REST ingestor local test config
│   ├── sbe-local.yaml          # SBE ingestor local test config
│   └── docker-env.yaml         # Docker test environment config
├── data/                       # Test data storage
│   ├── checkpoints/            # Test checkpoints
│   ├── logs/                   # Test logs
│   └── output/                 # Test output files
├── scripts/                    # Test utility scripts
│   ├── setup-test-env.sh       # Environment setup
│   ├── setup-localstack.sh     # LocalStack resource creation
│   └── run-all-tests.sh        # Test runner
├── unit/                       # Unit tests
│   ├── test_rest_client.py     # Direct REST client test
│   └── test_sbe_client.py      # Direct SBE client test
├── integration/                # Integration tests
│   └── test_full_services.py   # Full service integration test
├── e2e/                        # End-to-end tests
│   └── test_pipeline.py        # Complete pipeline test
└── docker-compose.test.yml     # Docker test environment
```

## Quick Start

### 1. Setup Test Environment
```bash
cd test/
./scripts/setup-test-env.sh
```

### 2. Run Unit Tests (No Dependencies)
```bash
# Test REST client directly
python unit/test_rest_client.py

# Test SBE client directly  
python unit/test_sbe_client.py
```

### 3. Run Integration Tests (Local Dependencies)
```bash
# Test full services
python integration/test_full_services.py
```

### 4. Run E2E Tests (Docker Environment)
```bash
# Start Docker environment
docker-compose -f docker-compose.test.yml up -d

# Setup AWS resources
./scripts/setup-localstack.sh

# Run end-to-end tests
python e2e/test_pipeline.py
```

### 5. Run All Tests
```bash
./scripts/run-all-tests.sh
```

## Test Categories

### Unit Tests (`unit/`)
- Test individual components in isolation
- No external dependencies required
- Fast execution (< 30 seconds each)

### Integration Tests (`integration/`)
- Test services with minimal dependencies
- May require local file system or mock services
- Medium execution time (1-5 minutes each)

### End-to-End Tests (`e2e/`)
- Test complete data pipeline
- Requires full Docker environment
- Longer execution time (5-15 minutes)

## Configuration Files

### `configs/rest-local.yaml`
Configuration for testing REST ingestor locally without Docker.

### `configs/sbe-local.yaml`
Configuration for testing SBE ingestor locally without Docker.

### `configs/docker-env.yaml`
Environment variables and settings for Docker-based testing.

## Data Management

### Test Data (`data/`)
- Automatically created during tests
- Safe to delete between test runs
- Gitignored to avoid committing test artifacts

### Logs (`data/logs/`)
- Service logs from test runs
- Useful for debugging test failures
- Automatically rotated

## Environment Variables

Create `.env` file in test directory:
```bash
# Binance API (required for SBE tests)
BINANCE_API_KEY=your_test_api_key
BINANCE_API_SECRET=your_test_api_secret

# AWS LocalStack
AWS_ACCESS_KEY_ID=test
AWS_SECRET_ACCESS_KEY=test
AWS_DEFAULT_REGION=us-east-1

# Test settings
TEST_DURATION=30
LOG_LEVEL=DEBUG
```

## Best Practices

1. **Run tests in order**: unit → integration → e2e
2. **Clean environment**: Delete `data/` between major test runs
3. **Isolated testing**: Each test should be independent
4. **Resource cleanup**: Tests should clean up after themselves
5. **Deterministic**: Tests should produce consistent results

## Troubleshooting

### Common Issues

**Import Errors**:
```bash
# Ensure you're in the test directory
cd test/
# Or add the project root to PYTHONPATH
export PYTHONPATH=/path/to/bitcoin_datapipeline:$PYTHONPATH
```

**SBE Decoder Not Found**:
```bash
# Build the decoder
cd ../services/sbe-ingestor
./build_sbe_decoder.sh
```

**Docker Issues**:
```bash
# Reset Docker environment
docker-compose -f docker-compose.test.yml down
docker system prune -f
docker-compose -f docker-compose.test.yml up -d
```

**LocalStack Connection**:
```bash
# Check LocalStack is running
curl http://localhost:4566/health
# Recreate resources
./scripts/setup-localstack.sh
```

## CI/CD Integration

This test structure is designed for CI/CD pipelines:

```yaml
# GitHub Actions example
- name: Unit Tests
  run: cd test && python unit/test_rest_client.py

- name: Integration Tests  
  run: cd test && python integration/test_full_services.py

- name: E2E Tests
  run: |
    cd test
    docker-compose -f docker-compose.test.yml up -d
    ./scripts/setup-localstack.sh
    python e2e/test_pipeline.py
```