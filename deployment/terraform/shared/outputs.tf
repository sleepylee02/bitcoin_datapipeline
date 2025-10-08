# Shared Terraform Outputs
# These outputs are used by environment-specific configurations

output "terraform_state_bucket" {
  description = "S3 bucket for Terraform state storage"
  value       = aws_s3_bucket.terraform_state.bucket
}

output "terraform_state_bucket_arn" {
  description = "ARN of S3 bucket for Terraform state"
  value       = aws_s3_bucket.terraform_state.arn
}

output "terraform_state_lock_table" {
  description = "DynamoDB table for Terraform state locking"
  value       = aws_dynamodb_table.terraform_state_lock.name
}

output "terraform_state_lock_table_arn" {
  description = "ARN of DynamoDB table for state locking"
  value       = aws_dynamodb_table.terraform_state_lock.arn
}

output "terraform_state_kms_key_id" {
  description = "KMS key ID for Terraform state encryption"
  value       = aws_kms_key.terraform_state.key_id
}

output "terraform_state_kms_key_arn" {
  description = "KMS key ARN for Terraform state encryption"
  value       = aws_kms_key.terraform_state.arn
}