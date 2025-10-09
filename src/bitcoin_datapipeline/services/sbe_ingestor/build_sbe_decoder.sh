#!/bin/bash
# Build script for Binance SBE C++ decoder extension.
#
# This script compiles the high-performance C++ extension for decoding
# Binance SBE binary WebSocket messages following the official Binance
# SBE C++ sample app patterns.
#
# Reference: https://github.com/binance/binance-sbe-cpp-sample-app

set -e  # Exit on any error

echo "🔧 Building Binance SBE C++ Decoder Extension (Schema 1:0)..."

# Check if we're in a virtual environment
if [[ "$VIRTUAL_ENV" == "" ]]; then
    echo "⚠️  Warning: Not in a virtual environment. Consider activating .venv"
fi

# Check for required dependencies
echo "🔍 Checking dependencies..."
if ! command -v c++ &> /dev/null; then
    echo "❌ Error: C++ compiler not found. Please install build-essential or equivalent."
    exit 1
fi

# Check C++20 support
if ! echo 'int main(){}' | c++ -std=c++20 -x c++ - -o /tmp/test_cpp20 2>/dev/null; then
    echo "❌ Error: C++20 support required but not available."
    echo "    Please update your compiler (GCC 10+ or Clang 10+)"
    exit 1
fi
rm -f /tmp/test_cpp20

# Change to SBE decoder directory
cd src/sbe_decoder

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build/ dist/ *.egg-info/ *.so

# Build the extension with optimizations
echo "🏗️  Building optimized C++ extension..."
if [[ "$VIRTUAL_ENV" != "" ]]; then
    PYTHON_CMD="$VIRTUAL_ENV/bin/python"
else
    PYTHON_CMD="python3"
fi

# Build with performance optimizations for trading applications
CPPFLAGS="-O3 -march=native -ffast-math -DNDEBUG" $PYTHON_CMD setup.py build_ext --inplace

# Install the extension
echo "📦 Installing extension..."
if "$PYTHON_CMD" -m pip --version >/dev/null 2>&1; then
    "$PYTHON_CMD" -m pip install -e .
else
    echo "⚠️  pip not available for $PYTHON_CMD; skipping editable install"
fi

echo "✅ Binance SBE decoder extension built successfully!"
echo ""
echo "🧪 Testing the extension..."
if $PYTHON_CMD -c "
from sbe_decoder_cpp import SBEDecoder
import sbe_decoder_cpp

decoder = SBEDecoder()
print(f'✅ SBE decoder loaded successfully!')
print(f'📋 Schema ID: {sbe_decoder_cpp.EXPECTED_SCHEMA_ID}')
print(f'📋 Schema Version: {sbe_decoder_cpp.EXPECTED_SCHEMA_VERSION}')
print(f'📋 Supported templates:')
print(f'   - Trade Stream: {sbe_decoder_cpp.TRADES_STREAM_EVENT}')
print(f'   - Best Bid/Ask: {sbe_decoder_cpp.BEST_BID_ASK_STREAM_EVENT}')
print(f'   - Depth Diff: {sbe_decoder_cpp.DEPTH_DIFF_STREAM_EVENT}')
"; then
    echo ""
    echo "🎉 All tests passed! The SBE decoder is ready for production use."
else
    echo ""
    echo "❌ Extension test failed. Please check the build output for errors."
    exit 1
fi

echo ""
echo "📋 Usage Notes:"
echo "   - This decoder supports Binance SBE WebSocket streams (schema 1:0)"
echo "   - Optimized for ultra-low latency trading applications"
echo "   - Supports trade, best bid/ask, and depth diff stream messages"
echo "   - Use decode_message() for automatic message type detection"
echo ""
echo "🔗 WebSocket endpoint: wss://stream-sbe.binance.com/stream"
echo "📚 Documentation: https://developers.binance.com/docs/binance-spot-api-docs/sbe-market-data-streams"
