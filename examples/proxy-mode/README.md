# Proxy Mode Example

Deploys Portal with proxy mode enabled. When a module is not found locally, Portal forwards the request to the public Terraform Registry.

This example configures:

- `proxy_enabled = true` to activate proxy fallback
- `proxy_allow_list` to restrict proxying to `hashicorp/` and `myorg/` namespaces
- `proxy_deny_list` to block `internal/` modules from being proxied (deny takes precedence over allow)

The file also includes commented-out resources showing how to provision an ACM certificate and Route 53 DNS records for the custom domain. Uncomment those blocks if you manage DNS in Route 53.

## Usage

```bash
terraform init
terraform plan
terraform apply
```

Replace `domain_name` and `certificate_arn` with values from your own AWS environment.
