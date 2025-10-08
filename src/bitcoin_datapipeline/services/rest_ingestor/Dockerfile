# REST Ingestor Service Dockerfile

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for checkpoints and logs
RUN mkdir -p /app/checkpoints /app/logs

# Set environment variables
ENV PYTHONPATH="/app"
ENV CONFIG_FILE="config/local.yaml"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Expose health check port
EXPOSE 8080

# Run the application
CMD ["python", "-m", "src.main"]