terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

module "portal" {
  source = "../.."

  domain_name     = "registry.example.com"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

  # To use the ACM certificate created below instead, replace the line above with:
  # certificate_arn = aws_acm_certificate_validation.registry.certificate_arn

  proxy_enabled    = true
  proxy_allow_list = ["hashicorp/", "myorg/"]
  proxy_deny_list  = ["internal/"]

  s3_bucket_name           = "my-portal-modules"
  token_table_name         = "my-portal-tokens"
  master_token_secret_name = "my-portal-master-token"
}

# -----------------------------------------------------------------------------
# Optional: Custom domain with Route 53 and ACM
#
# Uncomment the resources below to provision the ACM certificate and DNS
# records alongside the module. Replace the certificate_arn in the module
# block above as noted in the comment.
# -----------------------------------------------------------------------------

# data "aws_route53_zone" "main" {
#   name = "example.com"
# }
#
# resource "aws_acm_certificate" "registry" {
#   domain_name       = "registry.example.com"
#   validation_method = "DNS"
#
#   lifecycle {
#     create_before_destroy = true
#   }
# }
#
# resource "aws_route53_record" "cert_validation" {
#   for_each = {
#     for dvo in aws_acm_certificate.registry.domain_validation_options : dvo.domain_name => {
#       name   = dvo.resource_record_name
#       type   = dvo.resource_record_type
#       record = dvo.resource_record_value
#     }
#   }
#
#   zone_id = data.aws_route53_zone.main.zone_id
#   name    = each.value.name
#   type    = each.value.type
#   ttl     = 60
#   records = [each.value.record]
# }
#
# resource "aws_acm_certificate_validation" "registry" {
#   certificate_arn         = aws_acm_certificate.registry.arn
#   validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
# }
#
# resource "aws_route53_record" "registry" {
#   zone_id = data.aws_route53_zone.main.zone_id
#   name    = "registry.example.com"
#   type    = "A"
#
#   alias {
#     name                   = module.portal.custom_domain_regional_domain_name
#     zone_id                = module.portal.custom_domain_regional_zone_id
#     evaluate_target_health = false
#   }
# }
