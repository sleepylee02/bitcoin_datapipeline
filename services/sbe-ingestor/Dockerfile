# SBE Ingestor Service Dockerfile
# Multi-stage build for C++ SBE decoder compilation

FROM python:3.11-slim as builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    cmake \
    g++ \
    pybind11-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy SBE decoder source
COPY src/sbe_decoder/ ./sbe_decoder/

# Build SBE decoder
WORKDIR /app/sbe_decoder
RUN python setup.py build_ext --inplace

# Production stage
FROM python:3.11-slim

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Copy compiled SBE decoder from builder stage
COPY --from=builder /app/sbe_decoder/sbe_decoder_cpp.*.so ./src/sbe_decoder/

# Create directories for logs
RUN mkdir -p /app/logs

# Set environment variables
ENV PYTHONPATH="/app"
ENV CONFIG_FILE="config/local.yaml"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8081/health || exit 1

# Expose health check port
EXPOSE 8081

# Run the application
CMD ["python", "-m", "src.main"]