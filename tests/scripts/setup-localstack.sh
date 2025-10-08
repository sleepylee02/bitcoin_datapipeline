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
