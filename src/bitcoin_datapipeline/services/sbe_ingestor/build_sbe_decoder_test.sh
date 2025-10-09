#!/bin/bash
# Test build script for Binance SBE C++ decoder extension.
#
# This script builds the SBE decoder for testing/development environments
# using direct setup.py calls to avoid pip isolation issues.
# For production/MSA Docker builds, use build_sbe_decoder.sh instead.

set -e  # Exit on any error

echo "🔧 Building Binance SBE C++ Decoder Extension (Test Mode)..."

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

# Check if pybind11 is available in current environment
echo "🔍 Checking pybind11 availability..."
if ! python3 -c "import pybind11; print(f'✅ pybind11 found: {pybind11.__version__}')" 2>/dev/null; then
    echo "❌ Error: pybind11 not found in current environment."
    echo "    Make sure service dependencies are installed: pip install -r requirements.txt"
    exit 1
fi

# Change to SBE decoder directory
cd src/sbe_decoder

# Clean previous builds
echo "🧹 Cleaning previous builds..."
rm -rf build/ dist/ *.egg-info/ *.so

# Build the extension with optimizations using direct setup.py
echo "🏗️  Building optimized C++ extension (direct mode)..."
if [[ "$VIRTUAL_ENV" != "" ]]; then
    PYTHON_CMD="$VIRTUAL_ENV/bin/python"
else
    PYTHON_CMD="python3"
fi

# Build with performance optimizations for trading applications
CPPFLAGS="-O3 -march=native -ffast-math -DNDEBUG" $PYTHON_CMD setup.py build_ext --inplace

# For testing, we just build in-place and add to PYTHONPATH
# This completely avoids pip and works with the current environment
echo "📦 Extension built in-place (no installation needed for testing)..."
echo "    The .so file is available in the current directory"

echo "✅ Binance SBE decoder extension built successfully (test mode)!"
echo ""
echo "🧪 Testing the extension..."

# Test the extension by importing from current directory
if $PYTHON_CMD -c "
import sys
import os
sys.path.insert(0, os.getcwd())  # Add current directory to Python path

try:
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
except ImportError as e:
    print(f'❌ Import failed: {e}')
    import glob
    so_files = glob.glob('*.so')
    print(f'Available .so files: {so_files}')
    exit(1)
"; then
    echo ""
    echo "🎉 All tests passed! The SBE decoder is ready for testing use."
else
    echo ""
    echo "❌ Extension test failed. Please check the build output for errors."
    exit 1
fi

echo ""
echo "📋 Build Mode: TESTING/DEVELOPMENT"
echo "   - Uses setup.py build_ext --inplace (no installation)"
echo "   - Completely avoids pip isolation issues"
echo "   - .so file built in src/sbe_decoder/ directory"
echo "   - Suitable for local testing and development"
echo ""
echo "🐳 For Docker/MSA builds, use: ./build_sbe_decoder.sh"
echo "📚 Documentation: https://developers.binance.com/docs/binance-spot-api-docs/sbe-market-data-streams"