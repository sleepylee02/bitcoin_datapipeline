# Data Connector Service Dockerfile

FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create directories for logs
RUN mkdir -p /app/logs

# Set environment variables
ENV PYTHONPATH="/app"
ENV CONFIG_FILE="config/local.yaml"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8082/health || exit 1

# Expose health check port
EXPOSE 8082

# Run the application
CMD ["python", "-m", "src.main"]