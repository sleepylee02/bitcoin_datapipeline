#!/bin/bash
# Setup LocalStack resources for Bitcoin Pipeline testing
# This script creates AWS resources in LocalStack for E2E testing

set -e

echo "🚀 Bitcoin Pipeline - LocalStack Setup"
echo "======================================"

# Check if LocalStack is running
echo "⏳ Waiting for LocalStack to be ready..."
timeout=60
elapsed=0
until curl -s http://localhost:4566/health | grep -q "running"; do
    if [ $elapsed -ge $timeout ]; then
        echo "❌ LocalStack is not responding after ${timeout}s"
        echo "   Make sure LocalStack is running: docker run -p 4566:4566 localstack/localstack"
        exit 1
    fi
    echo "   Waiting for LocalStack... ($elapsed/${timeout}s)"
    sleep 2
    elapsed=$((elapsed + 2))
done

echo "✅ LocalStack is ready"

# Set AWS CLI to use LocalStack
export AWS_ACCESS_KEY_ID=test
export AWS_SECRET_ACCESS_KEY=test
export AWS_DEFAULT_REGION=us-east-1

echo "📊 Creating Kinesis streams..."
streams=(
    "market-trade-stream"
    "market-bestbidask-stream" 
    "market-depth-stream"
    "test-trade-stream"
    "test-bestbidask-stream"
    "test-depth-stream"
)

for stream in "${streams[@]}"; do
    echo "   Creating stream: $stream"
    aws --endpoint-url=http://localhost:4566 kinesis create-stream \
        --stream-name "$stream" \
        --shard-count 1 \
        --region us-east-1 2>/dev/null || echo "   ⚠️ Stream $stream may already exist"
done

echo "🪣 Creating S3 buckets..."
buckets=(
    "bitcoin-data-lake"
    "bitcoin-checkpoints"
    "test-bucket"
)

for bucket in "${buckets[@]}"; do
    echo "   Creating bucket: $bucket"
    aws --endpoint-url=http://localhost:4566 s3 mb "s3://$bucket" \
        --region us-east-1 2>/dev/null || echo "   ⚠️ Bucket $bucket may already exist"
done

# Create Redis-like service (using LocalStack Pro feature or mock)
echo "🔴 Setting up Redis mock..."
# Note: LocalStack Community doesn't include Redis, but we can document the expectation

echo ""
echo "✅ LocalStack setup complete!"
echo ""
echo "📋 Created Resources:"
echo "   Kinesis Streams:"
aws --endpoint-url=http://localhost:4566 kinesis list-streams --region us-east-1 --output table 2>/dev/null || echo "   (Unable to list streams)"

echo "   S3 Buckets:"
aws --endpoint-url=http://localhost:4566 s3 ls 2>/dev/null || echo "   (Unable to list buckets)"

echo ""
echo "🔗 LocalStack Endpoints:"
echo "   Health: http://localhost:4566/health"
echo "   Kinesis: aws --endpoint-url=http://localhost:4566 kinesis ..."
echo "   S3: aws --endpoint-url=http://localhost:4566 s3 ..."
echo ""
echo "📋 Next Steps:"
echo "   • Run E2E tests: pytest -m e2e"
echo "   • Check health: curl http://localhost:4566/health"
echo "   • Clean up: docker-compose down (if using docker-compose)"