# Basic Example

Deploys the registry with the minimum required configuration: a custom domain name and an ACM certificate ARN.

All optional features (proxy mode, custom bucket names, etc.) use their default values.

## Usage

```bash
terraform init
terraform plan
terraform apply
```

Replace `domain_name` and `certificate_arn` with values from your own AWS environment.
