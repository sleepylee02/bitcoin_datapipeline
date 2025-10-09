#!/bin/bash
# Context-aware development setup script for Bitcoin Data Pipeline
# This script sets up the local development environment for testing across all services

set -e

# Smart path resolution - always find project root regardless of execution location
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Bitcoin Pipeline - Development Setup"
echo "======================================="
echo "📍 Script location: $SCRIPT_DIR"
echo "📍 Project root: $PROJECT_ROOT"

cd "$PROJECT_ROOT"

# Check if we're in a virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "⚠️  Warning: Not in a virtual environment."
    echo "   It's recommended to activate a virtual environment first:"
    echo "   python3 -m venv venv && source venv/bin/activate"
    echo ""
    echo "   Continue anyway? (y/N)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        echo "❌ Setup cancelled. Please activate a virtual environment and try again."
        exit 1
    fi
fi

# Upgrade pip first
echo "📦 Upgrading pip..."
pip install --upgrade pip

# Install testing and development tools
echo "📦 Installing testing and development tools..."
pip install -r requirements-dev.txt

# Install dependencies from each service (using new paths)
echo "📦 Installing service dependencies..."
services=("rest_ingestor" "sbe_ingestor" "aggregator" "data_connector")
for service in "${services[@]}"; do
    service_path="src/bitcoin_datapipeline/services/$service"
    if [ -d "$service_path" ] && [ -f "$service_path/requirements.txt" ]; then
        echo "   Installing dependencies for $service..."
        pip install -r "$service_path/requirements.txt"
    else
        echo "   ⚠️ Skipping $service (no requirements.txt found)"
    fi
done

# Build SBE decoder (using test build for development)
echo "🔧 Building SBE decoder..."
cd "$PROJECT_ROOT/src/bitcoin_datapipeline/services/sbe_ingestor"
if [ -f "build_sbe_decoder_test.sh" ]; then
    chmod +x build_sbe_decoder_test.sh
    ./build_sbe_decoder_test.sh
    echo "✅ SBE decoder built successfully (test mode)"
else
    echo "❌ SBE decoder test build script not found"
    exit 1
fi

cd "$PROJECT_ROOT"

# Install project in development mode using pyproject.toml
echo "📦 Installing project in development mode..."
pip install -e .

# Verify installation by testing imports (using new paths)
echo "🧪 Verifying installation..."
python3 -c "
import sys
print(f'✅ Python version: {sys.version}')

try:
    from bitcoin_datapipeline.services.rest_ingestor.src.clients.binance_rest import BinanceRESTClient
    print('✅ REST client import successful')
except ImportError as e:
    print(f'❌ REST client import failed: {e}')

try:
    from bitcoin_datapipeline.services.sbe_ingestor.src.clients.binance_sbe import BinanceSBEClient
    print('✅ SBE client import successful')
except ImportError as e:
    print(f'❌ SBE client import failed: {e}')

try:
    import pytest
    print('✅ Pytest available')
except ImportError:
    print('❌ Pytest not available')
"

echo ""
echo "🎉 Development setup complete!"
echo ""
echo "📋 What you can do now:"
echo "   • Run unit tests: pytest tests/unit/test_rest_client.py"
echo "   • Run all tests: pytest"
echo "   • Run specific test: pytest tests/unit/ -v"
echo "   • Format code: black ."
echo "   • Check types: mypy src/"
echo ""
echo "📋 Service dependencies maintained separately:"
for service in src/bitcoin_datapipeline/services/*/requirements.txt; do
    if [ -f "$service" ]; then
        echo "   • $(dirname "$service")"
    fi
done
echo ""