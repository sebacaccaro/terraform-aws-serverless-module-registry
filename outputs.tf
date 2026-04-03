output "api_endpoint" {
  description = "API Gateway stage invoke URL"
  value       = aws_api_gateway_stage.main.invoke_url
}

output "api_id" {
  description = "API Gateway REST API ID"
  value       = aws_api_gateway_rest_api.main.id
}

output "s3_bucket_name" {
  description = "Name of the S3 modules bucket"
  value       = aws_s3_bucket.modules.id
}

output "s3_bucket_arn" {
  description = "ARN of the S3 modules bucket"
  value       = aws_s3_bucket.modules.arn
}

output "dynamodb_table_name" {
  description = "Name of the DynamoDB tokens table"
  value       = aws_dynamodb_table.tokens.name
}

output "master_token_secret_arn" {
  description = "ARN of the Secrets Manager master token secret"
  value       = aws_secretsmanager_secret.master_token.arn
}

output "api_gateway_domain_name" {
  description = "The execute-api regional hostname of the REST API"
  value       = "${aws_api_gateway_rest_api.main.id}.execute-api.${data.aws_region.current.id}.amazonaws.com"
}

output "custom_domain_regional_domain_name" {
  description = "Regional domain name of the custom domain for DNS CNAME/alias targeting"
  value       = aws_api_gateway_domain_name.custom.regional_domain_name
}

output "custom_domain_regional_zone_id" {
  description = "Regional hosted zone ID of the custom domain for Route 53 alias targeting"
  value       = aws_api_gateway_domain_name.custom.regional_zone_id
}
