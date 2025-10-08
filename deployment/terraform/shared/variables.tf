# Shared Terraform Variables
# These variables are used across all environments

variable "project_name" {
  description = "Name of the project, used for resource naming"
  type        = string
  default     = "bitcoin-pipeline"
}

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "availability_zones" {
  description = "List of availability zones to use"
  type        = list(string)
  default     = ["us-east-1a", "us-east-1b", "us-east-1c"]
}

# Global tags applied to all resources
variable "global_tags" {
  description = "Tags to apply to all resources"
  type        = map(string)
  default = {
    Project     = "bitcoin-data-pipeline"
    ManagedBy   = "terraform"
    Repository  = "bitcoin_datapipeline"
    Owner       = "data-engineering-team"
  }
}