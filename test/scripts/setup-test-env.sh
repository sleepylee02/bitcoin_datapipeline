#!/bin/bash
# Setup script for Bitcoin Pipeline test environment

set -e

echo "🚀 Setting up Bitcoin Pipeline Test Environment"
echo "=============================================="

# Get the project root directory (parent of test/)
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "📁 Project root: $PROJECT_ROOT"
echo "📁 Test directory: $TEST_DIR"

cd "$TEST_DIR"

# Create necessary test directories
echo "📁 Creating test directories..."
mkdir -p data/{logs,checkpoints,output}
mkdir -p configs
mkdir -p scripts

# Create environment file if it doesn't exist
if [ ! -f ".env" ]; then
    cp .env.template .env
    echo "✅ Created .env file from template"
    echo "⚠️  Please edit test/.env with your Binance API credentials"
else
    echo "✅ .env file already exists"
fi

# Setup Python virtual environment in project root
echo "🐍 Setting up Python environment..."
cd "$PROJECT_ROOT"
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ Created virtual environment"
else
    echo "✅ Virtual environment already exists"
fi

# Activate virtual environment
source venv/bin/activate

# Install test dependencies
echo "📦 Installing test dependencies..."
pip install --upgrade pip

# Basic test dependencies
pip install pytest pytest-asyncio aiohttp websockets

# Install dependencies for each service
services=("rest-ingestor" "sbe-ingestor" "aggregator")
for service in "${services[@]}"; do
    if [ -d "services/$service" ]; then
        echo "📦 Installing dependencies for $service..."
        cd "services/$service"
        if [ -f "requirements.txt" ]; then
            pip install -r requirements.txt
        fi
        cd "$PROJECT_ROOT"
    fi
done

# Build SBE decoder
echo "🔧 Building SBE decoder..."
cd "services/sbe-ingestor"
if [ -f "build_sbe_decoder.sh" ]; then
    chmod +x build_sbe_decoder.sh
    ./build_sbe_decoder.sh
    echo "✅ SBE decoder built successfully"
else
    echo "⚠️  SBE decoder build script not found"
fi
cd "$PROJECT_ROOT"

# Create LocalStack setup script
echo "🏗️  Creating LocalStack setup script..."
cat > "$TEST_DIR/scripts/setup-localstack.sh" << 'EOF'
#!/bin/bash
# Setup LocalStack resources for testing

set -e

echo "⏳ Waiting for LocalStack to be ready..."
until curl -s http://localhost:4566/health | grep -q "running"; do
    echo "   Waiting for LocalStack..."
    sleep 2
done

echo "📊 Creating Kinesis streams..."
streams=("market-trade-stream" "market-bestbidask-stream" "market-depth-stream" "test-trade-stream" "test-bestbidask-stream" "test-depth-stream")
for stream in "${streams[@]}"; do
    aws --endpoint-url=http://localhost:4566 kinesis create-stream \
        --stream-name "$stream" \
        --shard-count 1 \
        --region us-east-1 || echo "Stream $stream may already exist"
done

echo "🪣 Creating S3 buckets..."
buckets=("bitcoin-data-lake" "test-bucket")
for bucket in "${buckets[@]}"; do
    aws --endpoint-url=http://localhost:4566 s3 mb "s3://$bucket" \
        --region us-east-1 || echo "Bucket $bucket may already exist"
done

echo "✅ LocalStack setup complete"
echo "📋 Available streams:"
aws --endpoint-url=http://localhost:4566 kinesis list-streams --region us-east-1
echo "📋 Available buckets:"
aws --endpoint-url=http://localhost:4566 s3 ls
EOF

chmod +x "$TEST_DIR/scripts/setup-localstack.sh"

# Create test runner script
echo "🧪 Creating test runner script..."
cat > "$TEST_DIR/scripts/run-all-tests.sh" << 'EOF'
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
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
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
EOF

chmod +x "$TEST_DIR/scripts/run-all-tests.sh"

# Update test scripts to use correct paths
echo "🔧 Updating test scripts..."
cd "$TEST_DIR"

# Update unit tests to use proper imports
for test_file in unit/test_*.py; do
    if [ -f "$test_file" ]; then
        # Add project root to sys.path at the beginning
        sed -i '1i#!/usr/bin/env python3' "$test_file"
        sed -i '2i# Add project root to Python path' "$test_file"
        sed -i '3iimport sys' "$test_file"
        sed -i '4iimport os' "$test_file"
        sed -i '5iproject_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))' "$test_file"
        sed -i '6isys.path.insert(0, project_root)' "$test_file"
        sed -i '7i' "$test_file"
    fi
done

echo ""
echo "🎉 Test environment setup complete!"
echo ""
echo "📋 Next steps:"
echo "   1. Edit test/.env with your Binance API credentials"
echo "   2. Run unit tests: cd test && python unit/test_rest_client.py"
echo "   3. Run all tests: cd test && ./scripts/run-all-tests.sh"
echo "   4. For Docker tests: cd test && docker-compose -f docker-compose.test.yml up -d"
echo ""
echo "📁 Test directory structure:"
find "$TEST_DIR" -type f -name "*.py" -o -name "*.sh" -o -name "*.yml" | sort
echo ""