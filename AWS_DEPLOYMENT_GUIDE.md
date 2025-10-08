# Bitcoin Pipeline - AWS EC2 Deployment Guide

This guide explains how to deploy the ingestor services to AWS EC2 after successful local testing.

## Prerequisites

- Local testing completed successfully
- AWS account with appropriate permissions
- AWS CLI configured
- Docker images tested locally

## AWS Infrastructure Setup

### 1. EC2 Instance Requirements

#### Recommended Instance Types
- **Development**: t3.medium (2 vCPU, 4GB RAM)
- **Production**: c5.large (2 vCPU, 4GB RAM) or larger

#### Storage Requirements
- **Root volume**: 20GB gp3
- **Data volume**: 100GB+ gp3 (for checkpoints and logs)

#### Security Groups

Create security group with these rules:
```bash
# Inbound Rules
SSH (22)          - Your IP only
HTTP (8080)       - Internal/ALB only (REST health)
HTTP (8081)       - Internal/ALB only (SBE health)
HTTP (8082)       - Internal/ALB only (Aggregator health)

# Outbound Rules
All traffic (0-65535) - 0.0.0.0/0 (for Binance API access)
```

### 2. AWS Services Setup

#### 2.1 Kinesis Data Streams

```bash
# Create streams for SBE data
aws kinesis create-stream --stream-name market-trade-stream --shard-count 2 --region us-east-1
aws kinesis create-stream --stream-name market-bestbidask-stream --shard-count 1 --region us-east-1
aws kinesis create-stream --stream-name market-depth-stream --shard-count 2 --region us-east-1

# Verify streams
aws kinesis list-streams --region us-east-1
```

#### 2.2 S3 Bucket

```bash
# Create bucket for historical data
aws s3 mb s3://your-bitcoin-data-lake --region us-east-1

# Create folder structure
aws s3api put-object --bucket your-bitcoin-data-lake --key bronze/
aws s3api put-object --bucket your-bitcoin-data-lake --key checkpoints/
```

#### 2.3 ElastiCache Redis

```bash
# Create Redis cluster for features
aws elasticache create-cache-cluster \
    --cache-cluster-id bitcoin-features \
    --cache-node-type cache.t3.micro \
    --engine redis \
    --num-cache-nodes 1 \
    --region us-east-1
```

#### 2.4 RDS PostgreSQL (Optional)

```bash
# Create PostgreSQL for training data
aws rds create-db-instance \
    --db-instance-identifier bitcoin-pipeline-db \
    --db-instance-class db.t3.micro \
    --engine postgres \
    --master-username pipeline_user \
    --master-user-password your_secure_password \
    --allocated-storage 20 \
    --vpc-security-group-ids sg-your-security-group \
    --region us-east-1
```

## EC2 Instance Setup

### 1. Launch EC2 Instance

```bash
# Launch instance
aws ec2 run-instances \
    --image-id ami-0c55b159cbfafe1d0 \
    --count 1 \
    --instance-type c5.large \
    --key-name your-key-pair \
    --security-group-ids sg-your-security-group \
    --subnet-id subnet-your-subnet \
    --block-device-mappings '[
        {
            "DeviceName": "/dev/xvda",
            "Ebs": {
                "VolumeSize": 20,
                "VolumeType": "gp3"
            }
        },
        {
            "DeviceName": "/dev/xvdf", 
            "Ebs": {
                "VolumeSize": 100,
                "VolumeType": "gp3"
            }
        }
    ]' \
    --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=bitcoin-pipeline-ingestor}]' \
    --region us-east-1
```

### 2. Connect and Setup Instance

```bash
# SSH to instance
ssh -i your-key.pem ec2-user@your-instance-ip

# Update system
sudo yum update -y

# Install Docker
sudo yum install -y docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -a -G docker ec2-user

# Install Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/download/v2.20.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Install AWS CLI v2
curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Install build tools for SBE decoder
sudo yum groupinstall -y "Development Tools"
sudo yum install -y cmake3 python3-devel

# Mount data volume
sudo mkfs -t xfs /dev/xvdf
sudo mkdir /data
sudo mount /dev/xvdf /data
sudo chown ec2-user:ec2-user /data

# Add to fstab for persistence
echo '/dev/xvdf /data xfs defaults,nofail 0 2' | sudo tee -a /etc/fstab
```

### 3. Setup Application

```bash
# Clone repository
cd /data
git clone https://github.com/your-username/bitcoin_datapipeline.git
cd bitcoin_datapipeline

# Setup environment
mkdir -p logs data checkpoints

# Create production environment file
cat > .env << EOF
# Binance API Credentials
BINANCE_API_KEY=your_production_api_key
BINANCE_API_SECRET=your_production_api_secret

# AWS Configuration
AWS_DEFAULT_REGION=us-east-1
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key

# Production settings
LOG_LEVEL=INFO
ENVIRONMENT=production
EOF

# Set secure permissions
chmod 600 .env
```

## Production Configuration

### 1. Update Service Configurations

#### REST Ingestor Production Config
Create `services/rest-ingestor/config/prod.yaml`:

```yaml
binance:
  rest_base_url: "https://data-api.binance.vision"
  symbols: ["BTCUSDT", "ETHUSDT"]  # Add more symbols as needed
  rate_limit_requests_per_minute: 1200
  request_timeout_seconds: 30

aws:
  region: "us-east-1"
  s3_bucket: "your-bitcoin-data-lake"
  s3_bronze_prefix: "bronze"
  s3_checkpoint_prefix: "checkpoints"

scheduler:
  enabled: true
  collection_interval: "1h"
  data_types: ["aggTrades", "klines"]
  overlap_minutes: 5

checkpoint:
  storage_type: "s3"
  s3_bucket: "your-bitcoin-data-lake"
  s3_prefix: "checkpoints"

retry:
  max_attempts: 5
  initial_backoff_seconds: 2.0
  max_backoff_seconds: 120.0
  backoff_multiplier: 2.0
  jitter: true

logging:
  level: "INFO"
  format: "json"
  handlers: ["file", "console"]
  file_path: "/data/logs/rest-ingestor.log"

health:
  enabled: true
  port: 8080
  host: "0.0.0.0"

metrics:
  enable_prometheus: true
  prometheus_port: 9090
  enable_cloudwatch: true
  metrics_namespace: "BitcoinPipeline/RestIngestor"
```

#### SBE Ingestor Production Config
Create `services/sbe-ingestor/config/prod.yaml`:

```yaml
binance:
  sbe_ws_url: "wss://stream-sbe.binance.com:9443"
  api_key: "${BINANCE_API_KEY}"
  api_secret: "${BINANCE_API_SECRET}"
  symbols: ["BTCUSDT", "ETHUSDT"]
  stream_types: ["trade", "bestBidAsk", "depth"]
  reconnect_interval_seconds: 5
  heartbeat_interval_seconds: 30

aws:
  region: "us-east-1"

kinesis:
  streams:
    trade: "market-trade-stream"
    bestbidask: "market-bestbidask-stream"
    depth: "market-depth-stream"
  batch_size: 500
  flush_interval_seconds: 1
  max_retries: 5

retry:
  max_attempts: 10
  initial_backoff_seconds: 1.0
  max_backoff_seconds: 60.0
  backoff_multiplier: 2.0
  jitter: true

logging:
  level: "INFO"
  format: "json"
  handlers: ["file", "console"]
  file_path: "/data/logs/sbe-ingestor.log"

health:
  enabled: true
  port: 8081
  host: "0.0.0.0"

metrics:
  enable_prometheus: true
  prometheus_port: 9091
  enable_cloudwatch: true
  metrics_namespace: "BitcoinPipeline/SBEIngestor"
```

### 2. Docker Compose for Production

Create `docker-compose.prod.yml`:

```yaml
version: '3.8'

services:
  rest-ingestor:
    build:
      context: ./services/rest-ingestor
      dockerfile: Dockerfile
    ports:
      - "8080:8080"
      - "9090:9090"
    environment:
      - CONFIG_FILE=config/prod.yaml
    env_file:
      - .env
    volumes:
      - "/data/logs:/app/logs"
      - "/data/checkpoints:/app/checkpoints"
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

  sbe-ingestor:
    build:
      context: ./services/sbe-ingestor
      dockerfile: Dockerfile
    ports:
      - "8081:8081"
      - "9091:9091"
    environment:
      - CONFIG_FILE=config/prod.yaml
    env_file:
      - .env
    volumes:
      - "/data/logs:/app/logs"
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

  aggregator:
    build:
      context: ./services/aggregator
      dockerfile: Dockerfile
    ports:
      - "8082:8082"
      - "9092:9092"
    environment:
      - CONFIG_FILE=config/prod.yaml
    env_file:
      - .env
    volumes:
      - "/data/logs:/app/logs"
    restart: unless-stopped
    logging:
      driver: "json-file"
      options:
        max-size: "100m"
        max-file: "5"

networks:
  default:
    name: bitcoin_pipeline_prod
```

## Deployment Process

### 1. Build and Deploy

```bash
# Build SBE decoder on EC2
cd /data/bitcoin_datapipeline/services/sbe-ingestor
./build_sbe_decoder.sh

# Build Docker images
cd /data/bitcoin_datapipeline
docker-compose -f docker-compose.prod.yml build

# Start services
docker-compose -f docker-compose.prod.yml up -d

# Check services are running
docker-compose -f docker-compose.prod.yml ps
```

### 2. Verify Deployment

```bash
# Check health endpoints
curl http://localhost:8080/health
curl http://localhost:8081/health
curl http://localhost:8082/health

# Check logs
docker-compose -f docker-compose.prod.yml logs -f rest-ingestor
docker-compose -f docker-compose.prod.yml logs -f sbe-ingestor

# Check data flow
aws kinesis describe-stream --stream-name market-trade-stream --region us-east-1
aws s3 ls s3://your-bitcoin-data-lake/bronze/ --recursive
```

## Monitoring and Maintenance

### 1. CloudWatch Setup

```bash
# Install CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/amazon_linux/amd64/latest/amazon-cloudwatch-agent.rpm
sudo rpm -U ./amazon-cloudwatch-agent.rpm

# Configure CloudWatch
sudo /opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-config-wizard
```

### 2. Log Monitoring

```bash
# Setup log rotation
sudo cat > /etc/logrotate.d/bitcoin-pipeline << EOF
/data/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    notifempty
    create 644 ec2-user ec2-user
}
EOF
```

### 3. System Services

Create systemd service for auto-restart:

```bash
sudo cat > /etc/systemd/system/bitcoin-pipeline.service << EOF
[Unit]
Description=Bitcoin Pipeline Services
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/data/bitcoin_datapipeline
ExecStart=/usr/local/bin/docker-compose -f docker-compose.prod.yml up -d
ExecStop=/usr/local/bin/docker-compose -f docker-compose.prod.yml down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable bitcoin-pipeline.service
sudo systemctl start bitcoin-pipeline.service
```

## Security Considerations

### 1. IAM Roles

Create EC2 IAM role with minimal permissions:

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "kinesis:PutRecord",
                "kinesis:PutRecords",
                "kinesis:DescribeStream"
            ],
            "Resource": "arn:aws:kinesis:us-east-1:*:stream/market-*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject"
            ],
            "Resource": "arn:aws:s3:::your-bitcoin-data-lake/*"
        },
        {
            "Effect": "Allow",
            "Action": [
                "cloudwatch:PutMetricData"
            ],
            "Resource": "*"
        }
    ]
}
```

### 2. Network Security

- Use private subnets for EC2 instances
- Configure NAT Gateway for outbound access
- Implement VPC endpoints for AWS services
- Use Application Load Balancer for health checks

### 3. Secrets Management

Store sensitive data in AWS Secrets Manager:

```bash
# Store Binance API credentials
aws secretsmanager create-secret \
    --name "bitcoin-pipeline/binance-api" \
    --description "Binance API credentials" \
    --secret-string '{"api_key":"your_key","api_secret":"your_secret"}' \
    --region us-east-1
```

## Troubleshooting

### Common Issues

1. **SBE Connection Failures**
   - Check API key permissions
   - Verify network connectivity
   - Check Binance API status

2. **Kinesis Write Errors**
   - Verify IAM permissions
   - Check shard capacity
   - Monitor throttling metrics

3. **High Memory Usage**
   - Monitor Docker container resources
   - Implement memory limits
   - Check for memory leaks

4. **Disk Space Issues**
   - Set up log rotation
   - Monitor checkpoint growth
   - Implement data cleanup

### Performance Tuning

1. **Instance Scaling**
   - Monitor CPU/memory usage
   - Scale vertically for single instance
   - Consider horizontal scaling for high throughput

2. **Kinesis Optimization**
   - Increase shard count for higher throughput
   - Optimize batch sizes
   - Monitor shard utilization

3. **Network Optimization**
   - Use enhanced networking
   - Consider placement groups
   - Monitor network bandwidth

## Maintenance Procedures

### Daily Tasks
- Check service health endpoints
- Monitor CloudWatch metrics
- Review error logs

### Weekly Tasks  
- Analyze performance trends
- Review capacity utilization
- Update dependencies if needed

### Monthly Tasks
- Rotate credentials
- Review and optimize costs
- Update security patches

This completes the AWS deployment guide. Follow this step-by-step to deploy your Bitcoin Pipeline to production on AWS EC2.