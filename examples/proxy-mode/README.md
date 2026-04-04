# Proxy Mode Example

Deploys the registry with proxy mode enabled. When a module is not found locally, requests are forwarded to the public Terraform Registry.

This example configures:

- `proxy_enabled = true` to activate proxy fallback
- `proxy_allow_list` to restrict proxying to `hashicorp/` and `myorg/` namespaces
- `proxy_deny_list` to block `internal/` modules from being proxied (deny takes precedence over allow)

## Usage

```bash
terraform init
terraform plan
terraform apply
```

Replace `domain_name` and `certificate_arn` with values from your own AWS environment.
