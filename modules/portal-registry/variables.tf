variable "proxy_enabled" {
  description = "Enable proxy fallback to the public Terraform registry"
  type        = bool
  default     = false
}

variable "proxy_allow_list" {
  description = "Prefix expressions for modules eligible for proxy (e.g., ['hashicorp/', 'myorg/vpc'])"
  type        = list(string)
  default     = []
}

variable "proxy_deny_list" {
  description = "Prefix expressions for modules excluded from proxy"
  type        = list(string)
  default     = []
}

variable "s3_bucket_name" {
  description = "Override the default S3 bucket name"
  type        = string
  default     = ""
}

variable "token_table_name" {
  description = "Name of the DynamoDB table for storing API tokens"
  type        = string
  default     = "portal-tokens"
}

variable "master_token_secret_name" {
  description = "Name of the Secrets Manager secret for the master token"
  type        = string
}

variable "domain_name" {
  description = "Custom domain name for the Terraform registry (e.g., registry.example.com)"
  type        = string
}

variable "certificate_arn" {
  description = "ARN of a pre-existing ACM certificate that covers the custom domain name"
  type        = string
}
