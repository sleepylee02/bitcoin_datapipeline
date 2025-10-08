# Bitcoin Data Pipeline - Terraform Infrastructure

## Overview
This directory contains Terraform configurations for deploying the complete Bitcoin price prediction infrastructure on AWS.

## Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                    TERRAFORM INFRASTRUCTURE                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │    Network      │  │    Compute      │  │     Data        │  │
│  │                 │  │                 │  │                 │  │
│  │ • VPC           │  │ • ECS Cluster   │  │ • S3 Buckets    │  │
│  │ • Subnets       │  │ • ECS Services  │  │ • Kinesis       │  │
│  │ • Security Grps │  │ • Load Balancer │  │ • RDS Aurora    │  │
│  │ • NAT Gateways  │  │ • Auto Scaling  │  │ • ElastiCache   │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │   Monitoring    │  │     IAM         │  │   Deployment    │  │
│  │                 │  │                 │  │                 │  │
│  │ • CloudWatch    │  │ • Service Roles │  │ • ECR Repos     │  │
│  │ • Alarms        │  │ • Policies      │  │ • CodePipeline  │  │
│  │ • Dashboards    │  │ • Instance Prof │  │ • CodeBuild     │  │
│  │ • Log Groups    │  │ • Cross-Account │  │ • GitHub Actions│  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

## Directory Structure
```
terraform/
├── environments/
│   ├── dev/              # Development environment
│   ├── staging/          # Staging environment  
│   └── prod/             # Production environment
├── modules/
│   ├── networking/       # VPC, subnets, security groups
│   ├── compute/          # ECS cluster, services, ALB
│   ├── data/            # S3, Kinesis, RDS, Redis
│   ├── monitoring/      # CloudWatch, alarms, dashboards
│   ├── iam/             # IAM roles, policies, profiles
│   └── deployment/      # ECR, CI/CD pipeline
├── shared/
│   ├── backend.tf       # Terraform state configuration
│   ├── variables.tf     # Global variables
│   └── outputs.tf       # Global outputs
└── README.md           # This file
```

## Quick Start

### 1. Prerequisites
```bash
# Install Terraform
brew install terraform  # macOS
# or
sudo apt-get install terraform  # Ubuntu

# Install AWS CLI
pip install awscli

# Configure AWS credentials
aws configure
```

### 2. Initialize Backend
```bash
cd terraform/shared
terraform init
terraform plan
terraform apply  # Creates S3 bucket for state storage
```

### 3. Deploy Environment
```bash
# Development environment
cd terraform/environments/dev
terraform init
terraform plan -var-file="dev.tfvars"
terraform apply -var-file="dev.tfvars"

# Production environment  
cd terraform/environments/prod
terraform init
terraform plan -var-file="prod.tfvars"
terraform apply -var-file="prod.tfvars"
```

## Environment Configuration

### Development (dev.tfvars)
```hcl
environment = "dev"
region     = "us-east-1"

# Minimal resources for development
ecs_cluster_capacity_providers = ["FARGATE_SPOT"]
rds_instance_class = "db.t3.micro"
redis_node_type = "cache.t3.micro"
kinesis_shard_count = 1

# Cost optimization
enable_nat_gateway = false
multi_az = false
backup_retention_period = 1
```

### Production (prod.tfvars)
```hcl
environment = "prod"
region     = "us-east-1"

# High availability and performance
ecs_cluster_capacity_providers = ["FARGATE"]
rds_instance_class = "db.r6g.large"
redis_node_type = "cache.r6g.large"
kinesis_shard_count = 4

# Production settings
enable_nat_gateway = true
multi_az = true
backup_retention_period = 30
enable_deletion_protection = true
```

## Service Deployment

### ECS Services Configuration
```hcl
# All Bitcoin pipeline services
services = {
  sbe-ingestor = {
    image_tag = "latest"
    cpu      = 1024
    memory   = 2048
    desired_count = 2
    port     = 8081
    health_check_path = "/health"
  }
  
  rest-ingestor = {
    image_tag = "latest"
    cpu      = 512
    memory   = 1024
    desired_count = 1
    port     = 8080
    health_check_path = "/health"
  }
  
  aggregator = {
    image_tag = "latest"
    cpu      = 1536
    memory   = 3072
    desired_count = 2
    port     = 8082
    health_check_path = "/health"
    priority = "high"  # Critical service
  }
  
  data-connector = {
    image_tag = "latest"
    cpu      = 2048
    memory   = 4096
    desired_count = 1
    port     = 8083
    health_check_path = "/health"
  }
  
  inference = {
    image_tag = "latest"
    cpu      = 2048
    memory   = 4096
    desired_count = 3
    port     = 8085
    health_check_path = "/health"
    priority = "high"  # Critical service
  }
}
```

## Infrastructure Components

### 1. Networking Module
- **VPC**: Isolated network environment
- **Subnets**: Public/private across 3 AZs
- **Security Groups**: Service-specific firewall rules
- **NAT Gateways**: Outbound internet access for private services

### 2. Compute Module  
- **ECS Cluster**: Container orchestration
- **ECS Services**: Auto-scaling service definitions
- **Application Load Balancer**: Traffic distribution
- **Target Groups**: Health checking and routing

### 3. Data Module
- **S3 Buckets**: Data lake storage with lifecycle policies
- **Kinesis Data Streams**: Real-time event streaming
- **RDS Aurora PostgreSQL**: RDBMS for feature store
- **ElastiCache Redis**: Hot state cache

### 4. Monitoring Module
- **CloudWatch Logs**: Centralized logging
- **CloudWatch Metrics**: Custom and AWS metrics
- **CloudWatch Alarms**: Automated alerting
- **CloudWatch Dashboards**: Operational visibility

### 5. IAM Module
- **Service Roles**: ECS task execution and service roles
- **Policies**: Least-privilege access controls
- **Instance Profiles**: EC2 instance permissions

### 6. Deployment Module
- **ECR Repositories**: Container image storage
- **CodePipeline**: CI/CD automation
- **CodeBuild**: Container build and test

## Cost Management

### Development Environment
```yaml
Estimated Monthly Cost:
├── ECS Fargate Spot:     ~$30
├── RDS t3.micro:         ~$20
├── ElastiCache t3.micro: ~$15
├── S3 storage (100GB):   ~$3
├── Kinesis (1 shard):    ~$15
├── Data transfer:        ~$10
└── CloudWatch:           ~$5
Total: ~$98/month
```

### Production Environment
```yaml
Estimated Monthly Cost:
├── ECS Fargate:          ~$200
├── RDS r6g.large:        ~$150
├── ElastiCache r6g.large:~$100
├── S3 storage (1TB):     ~$25
├── Kinesis (4 shards):   ~$60
├── Data transfer:        ~$50
├── CloudWatch:           ~$20
├── Load Balancer:        ~$20
└── NAT Gateway:          ~$45
Total: ~$670/month
```

## Security Best Practices

### Network Security
- Private subnets for all application services
- Security groups with minimal required access
- VPC Flow Logs for network monitoring
- WAF protection for public endpoints

### Data Security
- Encryption at rest for all storage services
- Encryption in transit with TLS 1.2+
- S3 bucket policies with least privilege
- RDS encryption with AWS KMS

### Access Control
- IAM roles with minimal required permissions
- Cross-account access for CI/CD
- Resource-based policies where applicable
- Secrets stored in AWS Secrets Manager

## Operational Procedures

### Deployment Process
```bash
# 1. Plan infrastructure changes
terraform plan -var-file="${ENV}.tfvars" -out="plan.tfplan"

# 2. Review plan output
terraform show plan.tfplan

# 3. Apply infrastructure changes
terraform apply plan.tfplan

# 4. Verify deployment
terraform output
```

### Rollback Process
```bash
# 1. Revert to previous Terraform configuration
git checkout HEAD~1

# 2. Plan the rollback
terraform plan -var-file="${ENV}.tfvars"

# 3. Apply rollback
terraform apply -var-file="${ENV}.tfvars"
```

### State Management
```bash
# View current state
terraform state list

# Import existing resources
terraform import aws_s3_bucket.data_lake bucket-name

# Remove resources from state
terraform state rm aws_instance.deprecated_instance
```

## Monitoring and Alerting

### Key Metrics Tracked
- ECS service CPU and memory utilization
- RDS connection count and CPU utilization  
- Kinesis stream incoming records and iterator age
- Redis cache hit ratio and memory usage
- S3 bucket size and request metrics

### Alert Thresholds
- ECS CPU > 80% for 5 minutes
- RDS CPU > 70% for 10 minutes
- Kinesis iterator age > 1 minute
- Redis memory usage > 85%
- Application error rate > 5%

## Disaster Recovery

### Backup Strategy
- RDS automated backups with 30-day retention
- S3 cross-region replication for critical data
- ECS service configuration in version control
- Terraform state backup to separate S3 bucket

### Recovery Procedures
1. **RDS Recovery**: Point-in-time restore from backup
2. **S3 Recovery**: Cross-region replication failover
3. **ECS Recovery**: Redeploy services from Terraform
4. **Complete DR**: Deploy to alternate region

This Terraform infrastructure provides a production-ready, scalable, and cost-effective deployment platform for the Bitcoin price prediction pipeline.