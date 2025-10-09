#!/bin/bash
# Run all Bitcoin Pipeline tests

set -e

TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="$(cd "$TEST_DIR/.." && pwd)"

echo "🧪 Bitcoin Pipeline - Test Runner"
echo "================================"

cd "$TEST_DIR"

# Load environment
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Activate virtual environment
if [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
else
    echo "⚠️  Virtual environment not found. Run setup-test-env.sh first."
    exit 1
fi

# Add project to Python path
export PYTHONPATH="$PROJECT_ROOT:$PYTHONPATH"

echo "📍 Test directory: $TEST_DIR"
echo "📍 Project root: $PROJECT_ROOT"
echo "📍 Python path: $PYTHONPATH"

# Run unit tests
echo ""
echo "1️⃣ Running Unit Tests..."
echo "========================"

echo "🔧 Testing REST client..."
python unit/test_rest_client.py
echo ""

echo "🔧 Testing SBE client..."
python unit/test_sbe_client.py
echo ""

# Run integration tests
echo "2️⃣ Running Integration Tests..."
echo "==============================="

echo "🔧 Testing full services..."
python integration/test_full_services.py
echo ""

# Run e2e tests if Docker is available
if command -v docker-compose >/dev/null 2>&1; then
    echo "3️⃣ Running E2E Tests..."
    echo "======================="
    
    echo "🐳 Starting Docker environment..."
    docker-compose -f docker-compose.test.yml up -d
    
    echo "⏳ Waiting for services to be ready..."
    sleep 30
    
    echo "🏗️  Setting up LocalStack..."
    ./scripts/setup-localstack.sh
    
    if [ -f "e2e/test_pipeline.py" ]; then
        echo "🔧 Testing full pipeline..."
        python e2e/test_pipeline.py
    else
        echo "⚠️  E2E test not found, skipping..."
    fi
    
    echo "🧹 Cleaning up Docker..."
    docker-compose -f docker-compose.test.yml down
else
    echo "⚠️  Docker not available, skipping E2E tests"
fi

echo ""
echo "🎉 All tests completed!"
