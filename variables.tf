variable "proxy_enabled" {
  description = "Enable proxy fallback to the public Terraform registry"
  type        = bool
  default     = true
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

variable "master_token_secret_name" {
  description = "Name of the Secrets Manager secret for the master token"
  type        = string
  default     = "prtl-master-token"
}

variable "domain_name" {
  description = "Custom domain name for the registry (e.g., registry.example.com)"
  type        = string
  default     = "gateway-test.thron.com"
}

variable "certificate_arn" {
  description = "ARN of a pre-existing ACM certificate covering the custom domain name"
  type        = string
  default     = "arn:aws:acm:eu-west-1:116184089574:certificate/5338fb6b-545c-479f-a195-f49739175796"
}
