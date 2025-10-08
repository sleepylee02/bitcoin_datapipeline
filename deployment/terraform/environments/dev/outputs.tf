# Development Environment Outputs
# These outputs provide important information about the deployed infrastructure

# Networking Outputs
output "vpc_id" {
  description = "ID of the VPC"
  value       = module.networking.vpc_id
}

output "vpc_cidr_block" {
  description = "CIDR block of the VPC"
  value       = module.networking.vpc_cidr_block
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = module.networking.private_subnet_ids
}

# Compute Outputs
output "ecs_cluster_name" {
  description = "Name of the ECS cluster"
  value       = module.compute.ecs_cluster_name
}

output "ecs_cluster_arn" {
  description = "ARN of the ECS cluster"
  value       = module.compute.ecs_cluster_arn
}

output "load_balancer_dns_name" {
  description = "DNS name of the load balancer"
  value       = module.compute.load_balancer_dns_name
}

output "load_balancer_zone_id" {
  description = "Zone ID of the load balancer"
  value       = module.compute.load_balancer_zone_id
}

output "service_urls" {
  description = "URLs for accessing services"
  value = {
    sbe_ingestor    = "http://${module.compute.load_balancer_dns_name}:8081/health"
    rest_ingestor   = "http://${module.compute.load_balancer_dns_name}:8080/health"
    aggregator      = "http://${module.compute.load_balancer_dns_name}:8082/health"
    data_connector  = "http://${module.compute.load_balancer_dns_name}:8083/health"
  }
}

# Data Outputs
output "s3_data_lake_bucket_name" {
  description = "Name of the S3 data lake bucket"
  value       = module.data.s3_data_lake_bucket_name
}

output "s3_data_lake_bucket_arn" {
  description = "ARN of the S3 data lake bucket"
  value       = module.data.s3_data_lake_bucket_arn
}

output "rds_cluster_endpoint" {
  description = "RDS cluster endpoint"
  value       = module.data.rds_endpoint
  sensitive   = true
}

output "rds_cluster_reader_endpoint" {
  description = "RDS cluster reader endpoint"
  value       = module.data.rds_reader_endpoint
  sensitive   = true
}

output "redis_cluster_endpoint" {
  description = "Redis cluster endpoint"
  value       = module.data.redis_endpoint
  sensitive   = true
}

output "kinesis_stream_names" {
  description = "Names of Kinesis data streams"
  value       = module.data.kinesis_stream_names
}

output "kinesis_stream_arns" {
  description = "ARNs of Kinesis data streams"
  value       = module.data.kinesis_stream_arns
}

# IAM Outputs
output "ecs_task_execution_role_arn" {
  description = "ARN of ECS task execution role"
  value       = module.iam.ecs_task_execution_role_arn
}

output "ecs_task_role_arn" {
  description = "ARN of ECS task role"
  value       = module.iam.ecs_task_role_arn
}

# Deployment Outputs
output "ecr_repository_urls" {
  description = "URLs of ECR repositories"
  value       = module.deployment.ecr_repository_urls
}

output "codepipeline_name" {
  description = "Name of the CodePipeline"
  value       = module.deployment.codepipeline_name
}

# Monitoring Outputs
output "cloudwatch_dashboard_url" {
  description = "URL of the CloudWatch dashboard"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${module.monitoring.dashboard_name}"
}

output "sns_topic_arn" {
  description = "ARN of SNS topic for alerts"
  value       = module.monitoring.sns_topic_arn
}

# Connection Information for Development
output "development_connection_info" {
  description = "Connection information for development"
  value = {
    rds_endpoint    = module.data.rds_endpoint
    redis_endpoint  = module.data.redis_endpoint
    s3_bucket      = module.data.s3_data_lake_bucket_name
    kinesis_streams = module.data.kinesis_stream_names
    ecr_repositories = module.deployment.ecr_repository_urls
  }
  sensitive = true
}

# Quick Start Commands
output "quick_start_commands" {
  description = "Useful commands for development"
  value = {
    docker_login = "aws ecr get-login-password --region ${var.aws_region} | docker login --username AWS --password-stdin ${split("/", values(module.deployment.ecr_repository_urls)[0])[0]}"
    
    push_image_example = "docker tag your-service:latest ${values(module.deployment.ecr_repository_urls)[0]}:latest && docker push ${values(module.deployment.ecr_repository_urls)[0]}:latest"
    
    ecs_service_logs = "aws logs tail /aws/ecs/${var.project_name}-${var.environment} --follow"
    
    redis_connect = "redis-cli -h ${module.data.redis_endpoint} -p 6379"
    
    rds_connect = "psql -h ${module.data.rds_endpoint} -U bitcoin_user -d bitcoin_${var.environment}"
  }
}

# Resource Summary
output "resource_summary" {
  description = "Summary of deployed resources"
  value = {
    environment      = var.environment
    region          = var.aws_region
    vpc_id          = module.networking.vpc_id
    ecs_cluster     = module.compute.ecs_cluster_name
    rds_cluster     = module.data.rds_cluster_id
    redis_cluster   = module.data.redis_cluster_id
    s3_bucket       = module.data.s3_data_lake_bucket_name
    service_count   = length(var.services)
    estimated_cost  = "~$98/month (development configuration)"
  }
}