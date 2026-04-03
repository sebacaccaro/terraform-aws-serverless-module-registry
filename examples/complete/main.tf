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

  proxy_enabled    = true
  proxy_allow_list = ["hashicorp/", "myorg/"]
  proxy_deny_list  = ["internal/"]

  s3_bucket_name           = "my-portal-modules"
  token_table_name         = "my-portal-tokens"
  master_token_secret_name = "my-portal-master-token"
}
