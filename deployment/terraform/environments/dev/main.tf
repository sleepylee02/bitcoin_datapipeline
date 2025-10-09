# Development Environment Infrastructure
# This deploys all Bitcoin pipeline services in development configuration

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  backend "s3" {
    # Backend configuration will be set during terraform init
    # Using partial configuration - values provided via backend config file
    key            = "environments/dev/terraform.tfstate"
    encrypt        = true
    dynamodb_table = "bitcoin-pipeline-terraform-state-lock"
  }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = merge(var.global_tags, {
      Environment = var.environment
    })
  }
}

# Data source to get availability zones
data "aws_availability_zones" "available" {
  state = "available"
}

# Data source to get the Terraform state bucket (created by shared config)
data "terraform_remote_state" "shared" {
  backend = "s3"
  config = {
    bucket = "${var.project_name}-terraform-state-${var.aws_region}"
    key    = "shared/terraform.tfstate"
    region = var.aws_region
  }
}

# Networking Module
module "networking" {
  source = "../../modules/networking"

  project_name         = var.project_name
  environment         = var.environment
  aws_region          = var.aws_region
  availability_zones  = data.aws_availability_zones.available.names
  
  # Development-specific networking config
  vpc_cidr           = var.vpc_cidr
  enable_nat_gateway = var.enable_nat_gateway
  single_nat_gateway = true  # Cost optimization for dev
  
  tags = var.global_tags
}

# Data Module (S3, Kinesis, RDS, Redis)
module "data" {
  source = "../../modules/data"

  project_name   = var.project_name
  environment    = var.environment
  aws_region     = var.aws_region
  
  # Networking
  vpc_id              = module.networking.vpc_id
  private_subnet_ids  = module.networking.private_subnet_ids
  database_subnet_ids = module.networking.database_subnet_ids
  
  # Development-specific data config
  rds_instance_class         = var.rds_instance_class
  rds_allocated_storage      = var.rds_allocated_storage
  rds_multi_az              = var.rds_multi_az
  rds_backup_retention_days = var.rds_backup_retention_days
  
  redis_node_type           = var.redis_node_type
  redis_num_cache_nodes     = var.redis_num_cache_nodes
  
  kinesis_shard_count       = var.kinesis_shard_count
  kinesis_retention_period  = var.kinesis_retention_period
  
  s3_lifecycle_enabled      = var.s3_lifecycle_enabled
  
  tags = var.global_tags
}

# IAM Module
module "iam" {
  source = "../../modules/iam"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  
  # Data resources for IAM policies
  s3_bucket_arns         = module.data.s3_bucket_arns
  kinesis_stream_arns    = module.data.kinesis_stream_arns
  rds_cluster_arn        = module.data.rds_cluster_arn
  redis_cluster_arn      = module.data.redis_cluster_arn
  
  tags = var.global_tags
}

# Compute Module (ECS, ALB, Auto Scaling)
module "compute" {
  source = "../../modules/compute"

  project_name   = var.project_name
  environment    = var.environment
  aws_region     = var.aws_region
  
  # Networking
  vpc_id             = module.networking.vpc_id
  public_subnet_ids  = module.networking.public_subnet_ids
  private_subnet_ids = module.networking.private_subnet_ids
  
  # Security
  ecs_security_group_id = module.networking.ecs_security_group_id
  alb_security_group_id = module.networking.alb_security_group_id
  
  # IAM
  ecs_task_execution_role_arn = module.iam.ecs_task_execution_role_arn
  ecs_task_role_arn          = module.iam.ecs_task_role_arn
  
  # Environment-specific compute config
  ecs_cluster_capacity_providers = var.ecs_cluster_capacity_providers
  services                      = var.services
  
  # Data connections
  rds_endpoint       = module.data.rds_endpoint
  redis_endpoint     = module.data.redis_endpoint
  kinesis_streams    = module.data.kinesis_streams
  s3_bucket_name     = module.data.s3_data_lake_bucket_name
  
  tags = var.global_tags
}

# Monitoring Module
module "monitoring" {
  source = "../../modules/monitoring"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  
  # Resources to monitor
  ecs_cluster_name    = module.compute.ecs_cluster_name
  ecs_service_names   = module.compute.ecs_service_names
  rds_cluster_id      = module.data.rds_cluster_id
  redis_cluster_id    = module.data.redis_cluster_id
  kinesis_stream_names = module.data.kinesis_stream_names
  alb_arn_suffix      = module.compute.alb_arn_suffix
  
  # Notification settings
  alert_email = var.alert_email
  
  tags = var.global_tags
}

# Deployment Module (ECR, CI/CD)
module "deployment" {
  source = "../../modules/deployment"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  
  # ECS integration
  ecs_cluster_name = module.compute.ecs_cluster_name
  ecs_services     = var.services
  
  # Source code integration
  github_repository = var.github_repository
  github_branch     = var.github_branch
  
  tags = var.global_tags
}