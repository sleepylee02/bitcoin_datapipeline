# Development Environment Configuration
# This file contains development-specific variable values

# Basic Configuration
project_name = "bitcoin-pipeline"
environment  = "dev"
aws_region   = "us-east-1"

# Networking - Development optimized for cost
vpc_cidr           = "10.0.0.0/16"
enable_nat_gateway = false  # Use internet gateway only to save costs

# Database Configuration - Minimal for development
rds_instance_class         = "db.t3.micro"
rds_allocated_storage      = 20
rds_multi_az              = false
rds_backup_retention_days = 1

# Redis Configuration - Single node for development
redis_node_type       = "cache.t3.micro"
redis_num_cache_nodes = 1

# Kinesis Configuration - Single shard for development
kinesis_shard_count      = 1
kinesis_retention_period = 24

# S3 Configuration
s3_lifecycle_enabled = true

# ECS Configuration - Use Fargate Spot for cost optimization
ecs_cluster_capacity_providers = ["FARGATE_SPOT"]

# Service Configuration - Reduced resources for development
services = {
  sbe-ingestor = {
    image_tag         = "latest"
    cpu              = 512    # 0.5 vCPU
    memory           = 1024   # 1 GB
    desired_count    = 1
    port             = 8081
    health_check_path = "/health"
    priority         = "normal"
    environment_variables = {
      CONFIG_FILE         = "config/local.yaml"
      LOG_LEVEL          = "DEBUG"
      ENABLE_MOCK_DATA   = "true"   # Use mock data in dev
    }
  }
  
  rest-ingestor = {
    image_tag         = "latest"
    cpu              = 256    # 0.25 vCPU
    memory           = 512    # 0.5 GB
    desired_count    = 1
    port             = 8080
    health_check_path = "/health"
    priority         = "normal"
    environment_variables = {
      CONFIG_FILE               = "config/local.yaml"
      LOG_LEVEL                = "DEBUG"
      COLLECTION_INTERVAL      = "5m"   # More frequent for dev testing
    }
  }
  
  aggregator = {
    image_tag         = "latest"
    cpu              = 512    # 0.5 vCPU
    memory           = 1024   # 1 GB
    desired_count    = 1
    port             = 8082
    health_check_path = "/health"
    priority         = "high"
    environment_variables = {
      CONFIG_FILE                = "config/local.yaml"
      LOG_LEVEL                 = "DEBUG"
      REDIS_MAX_CONNECTIONS     = "10"
      FEATURE_UPDATE_INTERVAL   = "2s"
    }
  }
  
  data-connector = {
    image_tag         = "latest"
    cpu              = 512    # 0.5 vCPU
    memory           = 1024   # 1 GB
    desired_count    = 1
    port             = 8083
    health_check_path = "/health"
    priority         = "normal"
    environment_variables = {
      CONFIG_FILE           = "config/local.yaml"
      LOG_LEVEL            = "DEBUG"
      ETL_BATCH_SIZE       = "1000"     # Smaller batches for dev
      PROCESSING_INTERVAL  = "10m"      # More frequent processing
    }
  }
  
  # Note: inference service will be added once implemented
  # inference = {
  #   image_tag         = "latest"
  #   cpu              = 512
  #   memory           = 1024
  #   desired_count    = 1
  #   port             = 8085
  #   health_check_path = "/health"
  #   priority         = "high"
  #   environment_variables = {
  #     CONFIG_FILE           = "config/local.yaml"
  #     LOG_LEVEL            = "DEBUG"
  #     MODEL_VERSION        = "latest"
  #     INFERENCE_INTERVAL   = "2s"
  #   }
  # }
}

# Monitoring Configuration
alert_email = "dev-alerts@yourcompany.com"

# CI/CD Configuration
github_repository = "your-github-org/bitcoin_datapipeline"
github_branch     = "develop"

# Development-specific tags
global_tags = {
  Project     = "bitcoin-data-pipeline"
  Environment = "dev"
  ManagedBy   = "terraform"
  Repository  = "bitcoin_datapipeline"
  Owner       = "data-engineering-team"
  Purpose     = "development-testing"
  AutoShutdown = "enabled"  # Allow automatic shutdown for cost savings
}