# Basic Example

Deploys Portal with the minimum required configuration: a custom domain name and an ACM certificate ARN.

All optional features (proxy mode, custom bucket names, etc.) use their default values.

The file also includes commented-out resources showing how to provision an ACM certificate and Route 53 DNS records for the custom domain. Uncomment those blocks if you manage DNS in Route 53 and want everything in one configuration.

## Usage

```bash
terraform init
terraform plan
terraform apply
```

Replace `domain_name` and `certificate_arn` with values from your own AWS environment.
