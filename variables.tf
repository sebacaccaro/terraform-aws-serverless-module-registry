variable "domain_name" {
  description = "Custom domain name for the registry (e.g., registry.example.com). Must be a valid DNS hostname. This domain is used for the API Gateway custom domain and service discovery endpoint."
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", var.domain_name))
    error_message = "The domain_name must be a valid DNS hostname (e.g., registry.example.com)."
  }
}

variable "certificate_arn" {
  description = "ARN of a pre-existing ACM certificate covering the custom domain. Must be a valid ACM certificate ARN (e.g., arn:aws:acm:us-east-1:123456789012:certificate/abcd1234-ef56-gh78-ij90-klmnopqrstuv)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-f0-9-]+$", var.certificate_arn))
    error_message = "The certificate_arn must be a valid ACM certificate ARN (e.g., arn:aws:acm:us-east-1:123456789012:certificate/abcd1234-ef56-gh78-ij90-klmnopqrstuv)."
  }
}

variable "proxy_enabled" {
  description = "Enable proxy fallback to the public Terraform Registry when a module is not found locally. When set to false (the default), only modules uploaded directly to Portal are served."
  type        = bool
  default     = false
}

variable "proxy_allow_list" {
  description = "Prefix expressions for modules eligible for proxying (e.g., [\"hashicorp/\", \"myorg/vpc\"]). When the list is empty and proxy is enabled, all modules are eligible for proxying. Each entry is matched as a prefix against the module's namespace/name path."
  type        = list(string)
  default     = []
}

variable "proxy_deny_list" {
  description = "Prefix expressions for modules excluded from proxying (e.g., [\"internal/\", \"private/secrets\"]). Deny list takes precedence over allow list. Each entry is matched as a prefix against the module's namespace/name path."
  type        = list(string)
  default     = []
}

variable "s3_bucket_name" {
  description = "Override the default S3 bucket name for storing module packages. When empty (the default), the bucket is named portal-modules-{account_id} using the current AWS account ID."
  type        = string
  default     = ""
}

variable "token_table_name" {
  description = "Name of the DynamoDB table for storing API tokens. Defaults to portal-tokens. Change this if you need to avoid naming conflicts with existing DynamoDB tables in your account."
  type        = string
  default     = "portal-tokens"
}

variable "master_token_secret_name" {
  description = "Name of the Secrets Manager secret for the master token. Defaults to prtl-master-token. The master token is used for administrative operations such as creating and revoking API tokens."
  type        = string
  default     = "prtl-master-token"
}
