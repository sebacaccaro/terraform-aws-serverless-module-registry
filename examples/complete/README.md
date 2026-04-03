# Complete Example

Deploys Portal with all optional features configured:

- Proxy mode enabled with allow and deny lists
- Custom S3 bucket name
- Custom DynamoDB token table name
- Custom Secrets Manager master token secret name

The file also includes commented-out resources showing how to provision an ACM certificate and Route 53 DNS records for the custom domain. Uncomment those blocks if you manage DNS in Route 53 and want a fully self-contained setup.

## Usage

```bash
terraform init
terraform plan
terraform apply
```

Replace `domain_name`, `certificate_arn`, and the custom resource names with values appropriate for your AWS environment.
