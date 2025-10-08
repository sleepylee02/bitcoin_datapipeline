#!/bin/bash
# Run all Bitcoin Pipeline tests

set -e

# Context-aware path resolution
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$TESTS_DIR/.." && pwd)"

echo "🧪 Bitcoin Pipeline - Test Runner"
echo "================================"
echo "📍 Script location: $SCRIPT_DIR"
echo "📍 Tests directory: $TESTS_DIR"
echo "📍 Project root: $PROJECT_ROOT"

cd "$TESTS_DIR"

# Load environment
if [ -f ".env" ]; then
    set -a
    source .env
    set +a
fi

# Activate virtual environment
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
else
    echo "⚠️  Virtual environment not found. Run setup-test-env.sh first."
    exit 1
fi

# Add src to Python path for new structure
export PYTHONPATH="$PROJECT_ROOT/src:$PYTHONPATH"

# Alternative: Run all tests with pytest discovery
echo "💡 Alternative: Run 'pytest' from project root for automatic test discovery"

# Run unit tests
echo ""
echo "1️⃣ Running Unit Tests..."
echo "========================"

echo "🔧 Testing REST client..."
pytest unit/test_rest_client.py -v
echo ""

echo "🔧 Testing SBE client..."
pytest unit/test_sbe_client.py -v
echo ""

# Run integration tests
echo "2️⃣ Running Integration Tests..."
echo "==============================="

echo "🔧 Testing full services..."
pytest integration/test_full_services.py -v
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
        pytest e2e/test_pipeline.py -v
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
