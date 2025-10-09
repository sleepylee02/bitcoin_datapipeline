# Development Environment Variables

variable "project_name" {
  description = "Name of the project"
  type        = string
  default     = "bitcoin-pipeline"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "global_tags" {
  description = "Global tags for all resources"
  type        = map(string)
  default = {
    Project     = "bitcoin-data-pipeline"
    Environment = "dev"
    ManagedBy   = "terraform"
    Repository  = "bitcoin_datapipeline"
    Owner       = "data-engineering-team"
  }
}

# Networking Configuration
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "enable_nat_gateway" {
  description = "Enable NAT Gateway for private subnets"
  type        = bool
  default     = false  # Cost optimization for dev
}

# RDS Configuration (Development - smaller instances)
variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.t3.micro"
}

variable "rds_allocated_storage" {
  description = "RDS allocated storage in GB"
  type        = number
  default     = 20
}

variable "rds_multi_az" {
  description = "Enable Multi-AZ for RDS"
  type        = bool
  default     = false  # Single AZ for dev
}

variable "rds_backup_retention_days" {
  description = "RDS backup retention period in days"
  type        = number
  default     = 1  # Minimal backup for dev
}

# Redis Configuration (Development)
variable "redis_node_type" {
  description = "ElastiCache Redis node type"
  type        = string
  default     = "cache.t3.micro"
}

variable "redis_num_cache_nodes" {
  description = "Number of Redis cache nodes"
  type        = number
  default     = 1
}

# Kinesis Configuration (Development)
variable "kinesis_shard_count" {
  description = "Number of Kinesis shards"
  type        = number
  default     = 1
}

variable "kinesis_retention_period" {
  description = "Kinesis data retention period in hours"
  type        = number
  default     = 24
}

# S3 Configuration
variable "s3_lifecycle_enabled" {
  description = "Enable S3 lifecycle policies"
  type        = bool
  default     = true
}

# ECS Configuration
variable "ecs_cluster_capacity_providers" {
  description = "ECS cluster capacity providers"
  type        = list(string)
  default     = ["FARGATE_SPOT"]  # Cost optimization for dev
}

# Service Configuration (Development - reduced resources)
variable "services" {
  description = "Configuration for Bitcoin pipeline services"
  type = map(object({
    image_tag           = string
    cpu                = number
    memory             = number
    desired_count      = number
    port               = number
    health_check_path  = string
    priority           = optional(string)
    environment_variables = optional(map(string))
  }))
  
  default = {
    sbe-ingestor = {
      image_tag         = "latest"
      cpu              = 512
      memory           = 1024
      desired_count    = 1
      port             = 8081
      health_check_path = "/health"
      priority         = "normal"
      environment_variables = {
        CONFIG_FILE = "config/local.yaml"
        LOG_LEVEL   = "DEBUG"
      }
    }
    
    rest-ingestor = {
      image_tag         = "latest"
      cpu              = 256
      memory           = 512
      desired_count    = 1
      port             = 8080
      health_check_path = "/health"
      priority         = "normal"
      environment_variables = {
        CONFIG_FILE = "config/local.yaml"
        LOG_LEVEL   = "DEBUG"
      }
    }
    
    aggregator = {
      image_tag         = "latest"
      cpu              = 512
      memory           = 1024
      desired_count    = 1
      port             = 8082
      health_check_path = "/health"
      priority         = "high"
      environment_variables = {
        CONFIG_FILE = "config/local.yaml"
        LOG_LEVEL   = "DEBUG"
      }
    }
    
    data-connector = {
      image_tag         = "latest"
      cpu              = 512
      memory           = 1024
      desired_count    = 1
      port             = 8083
      health_check_path = "/health"
      priority         = "normal"
      environment_variables = {
        CONFIG_FILE = "config/local.yaml"
        LOG_LEVEL   = "DEBUG"
      }
    }
    
    inference = {
      image_tag         = "latest"
      cpu              = 512
      memory           = 1024
      desired_count    = 1
      port             = 8085
      health_check_path = "/health"
      priority         = "high"
      environment_variables = {
        CONFIG_FILE = "config/local.yaml"
        LOG_LEVEL   = "DEBUG"
      }
    }
  }
}

# Monitoring Configuration
variable "alert_email" {
  description = "Email address for alerts"
  type        = string
  default     = "dev-team@company.com"
}

# CI/CD Configuration
variable "github_repository" {
  description = "GitHub repository for CI/CD"
  type        = string
  default     = "your-org/bitcoin_datapipeline"
}

variable "github_branch" {
  description = "GitHub branch for CI/CD"
  type        = string
  default     = "develop"
}