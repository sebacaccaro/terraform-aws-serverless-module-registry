module "portal_registry" {
  source = "./modules/portal-registry"

  proxy_enabled            = var.proxy_enabled
  proxy_allow_list         = var.proxy_allow_list
  proxy_deny_list          = var.proxy_deny_list
  domain_name              = var.domain_name
  certificate_arn          = var.certificate_arn
  master_token_secret_name = var.master_token_secret_name
}
