# Complete Example

Deploys the registry with all optional features configured:

- Proxy mode enabled with allow and deny lists
- Custom S3 bucket name
- Custom DynamoDB token table name
- Custom Secrets Manager master token secret name

## Usage

```bash
terraform init
terraform plan
terraform apply
```

Replace `domain_name`, `certificate_arn`, and the custom resource names with values appropriate for your AWS environment.
