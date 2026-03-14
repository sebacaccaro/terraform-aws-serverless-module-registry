output "api_endpoint" {
  description = "API Gateway stage invoke URL"
  value       = module.portal_registry.api_endpoint
}

output "api_id" {
  description = "API Gateway REST API ID"
  value       = module.portal_registry.api_id
}

output "s3_bucket_name" {
  description = "Name of the S3 modules bucket"
  value       = module.portal_registry.s3_bucket_name
}
output "api_gateway_domain_name" {
  description = "The execute-api regional hostname of the REST API"
  value       = module.portal_registry.api_gateway_domain_name
}

output "custom_domain_regional_domain_name" {
  description = "Regional domain name of the custom domain for DNS CNAME/alias targeting"
  value       = module.portal_registry.custom_domain_regional_domain_name
}
