# Backend configuration for development environment
# This file will be used by terraform init -backend-config=backend.tf

bucket         = "bitcoin-pipeline-terraform-state-us-east-1"
key           = "environments/dev/terraform.tfstate"
region        = "us-east-1"
encrypt       = true
dynamodb_table = "bitcoin-pipeline-terraform-state-lock"