# Portal — A private, fully serverless Terraform registry on AWS

A private, fully serverless Terraform module registry for AWS. Portal lets you host, distribute, and manage Terraform modules behind your own domain with token-based authentication. It can also proxy requests to the public Terraform Registry and pin specific module versions locally for reproducible, air-gap-friendly builds.

## ✨ Features

- 📦 Private module hosting with versioned uploads and S3-backed storage
- 🔐 Token-based authentication with three permission tiers (master, uploader, downloader)
- 🔀 Transparent proxy mode to the public Terraform Registry for modules not hosted locally
- 📌 Module pinning to snapshot public module versions into your private registry, so builds never break when upstream changes or goes down
- 🌐 Custom domain support with ACM certificate integration
- ⚡ Fully serverless — no infrastructure to manage, scales to zero when idle

## 📋 Prerequisites

- An AWS account with permissions to create API Gateway, Lambda, S3, DynamoDB, Secrets Manager, and IAM resources
- A registered domain name with a DNS zone you control
- An ACM certificate (in the same region) covering the custom domain
- Terraform >= 1.0
- AWS provider >= 5.0

## 🚀 Usage

```hcl
module "portal" {
  source = "your-registry/portal/aws"

  domain_name     = "registry.example.com"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/example-cert-id"
}
```

After applying, create a DNS CNAME or alias record pointing your `domain_name` to the `custom_domain_regional_domain_name` output.


### Optional: Route 53 DNS and ACM Certificate

If you manage your DNS in Route 53, you can provision the ACM certificate and DNS records alongside the module instead of creating them separately. This is entirely optional — you can use any DNS provider and supply a pre-existing certificate ARN.

```hcl
data "aws_route53_zone" "main" {
  name = "example.com"
}

resource "aws_acm_certificate" "registry" {
  domain_name       = "registry.example.com"
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  for_each = {
    for dvo in aws_acm_certificate.registry.domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  }

  zone_id = data.aws_route53_zone.main.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 60
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "registry" {
  certificate_arn         = aws_acm_certificate.registry.arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]
}

module "portal" {
  source = "your-registry/portal/aws"

  domain_name     = "registry.example.com"
  certificate_arn = aws_acm_certificate_validation.registry.certificate_arn
}

resource "aws_route53_record" "registry" {
  zone_id = data.aws_route53_zone.main.zone_id
  name    = "registry.example.com"
  type    = "A"

  alias {
    name                   = module.portal.custom_domain_regional_domain_name
    zone_id                = module.portal.custom_domain_regional_zone_id
    evaluate_target_health = false
  }
}
```

This creates the ACM certificate with DNS validation, waits for validation to complete, passes the validated certificate to Portal, and points the domain at the API Gateway custom domain via a Route 53 alias record.


## 📖 Use Cases

### 🔒 Private Registry

#### Configuring Terraform CLI Credentials

To authenticate Terraform CLI with your Portal registry, add a credentials block to your `~/.terraformrc` (Linux/macOS) or `%APPDATA%/terraform.rc` (Windows) file:

```hcl
credentials "registry.example.com" {
  token = "your-api-token"
}
```

Replace `registry.example.com` with your Portal custom domain and `your-api-token` with a valid downloader or uploader token.

#### Uploading a Module

Upload a module version using the REST API with a PUT request:

```bash
curl -X PUT \
  "https://registry.example.com/v1/modules/myorg/vpc/aws/1.0.0" \
  -H "Authorization: Bearer your-uploader-token" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @module.tar.gz
```

The module path follows the format `{namespace}/{name}/{system}/{version}` where version must be valid semver.

#### Referencing a Private Module

Use your Portal custom domain as the module source in Terraform configurations:

```hcl
module "vpc" {
  source  = "registry.example.com/myorg/vpc/aws"
  version = "1.0.0"
}
```

Terraform CLI uses the `/.well-known/terraform.json` service discovery endpoint to locate the module API automatically.

#### Token Permission Model

Portal uses three token permission levels:

| Token Type   | Upload Modules | Download Modules | Manage Tokens |
|-------------|:-:|:-:|:-:|
| master      | ✓ | ✓ | ✓ |
| uploader    | ✓ | ✓ |   |
| downloader  |   | ✓ |   |

- The **master** token is generated automatically during deployment and stored in AWS Secrets Manager. It has full access to all operations including token management.
- **Uploader** tokens can upload new module versions and download existing ones.
- **Downloader** tokens can only download modules. Use these for CI/CD pipelines and Terraform CLI credentials.

Create tokens using the master token:

```bash
curl -X POST \
  "https://registry.example.com/v1/tokens" \
  -H "Authorization: Bearer your-master-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-downloader", "permission": "downloader"}'
```


### 🔀 Proxy Mode

Portal can transparently proxy module download requests to the public Terraform Registry when a module is not found locally. This lets you use your private registry as a single source for both private and public modules.

Enable proxy mode by setting `proxy_enabled = true`:

```hcl
module "portal" {
  source = "your-registry/portal/aws"

  domain_name     = "registry.example.com"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/example-cert-id"

  proxy_enabled = true
}
```

#### Allow List

Restrict which public modules can be proxied using `proxy_allow_list`. Each entry is matched as a prefix against the module's `namespace/name` path. When the list is empty and proxy is enabled, all modules are eligible.

```hcl
proxy_allow_list = ["hashicorp/", "myorg/vpc"]
```

This allows proxying any module under the `hashicorp` namespace and the specific `myorg/vpc` module.

#### Deny List

Exclude specific modules from proxying using `proxy_deny_list`:

```hcl
proxy_deny_list = ["internal/", "private/secrets"]
```

This blocks proxying for any module under the `internal` namespace and the specific `private/secrets` module.

> The deny list takes precedence over the allow list. If a module matches both lists, it will not be proxied.


### 📌 Module Pinning

When proxy mode is enabled, module downloads are forwarded to the public Terraform Registry on every request. That means your `terraform apply` depends on the public registry being available and serving the same artifact every time. Module pinning removes that dependency.

Pinning a module version downloads the archive from the public registry once and stores it in your Portal S3 bucket. From that point on, Portal serves the local copy directly — it stops proxying that module version entirely. Your Terraform runs use the exact artifact you pinned, regardless of whether the public registry is available or whether the upstream maintainer has yanked or replaced the release.

This is particularly useful for:
- Production environments where you need reproducible, hermetic builds
- Air-gapped or restricted networks that can't reach the public registry at apply time
- Locking down a known-good version of a third-party module before rolling it out

Pin a module version with a single API call:

```bash
curl -X POST \
  "https://registry.example.com/v1/pins/hashicorp/consul/aws/0.12.0" \
  -H "Authorization: Bearer your-master-token"
```

The path follows the format `/v1/pins/{namespace}/{name}/{system}/{version}`. After pinning, any `terraform init` that requests `hashicorp/consul/aws` version `0.12.0` through your registry will get the locally stored copy.


## 📡 API Reference

The complete API specification is available in the bundled [`openapi.json`](openapi.json) file. This OpenAPI/Swagger document is the authoritative reference for all endpoints, request/response schemas, and error codes.

The API is organized into four categories:

- **Module operations** — Upload, download, list, and query module versions (`/v1/modules/...`)
- **Token management** — Create, list, and revoke API tokens (`/v1/tokens/...`)
- **Module pinning** — Pin public registry modules locally (`/v1/pins/...`)
- **Service discovery** — Terraform CLI service discovery endpoint (`/.well-known/terraform.json`)

All API requests (except service discovery) require a Bearer token in the `Authorization` header. See the [Token Permission Model](#token-permission-model) section for details on which token types authorize which operations.

Quick-start examples:

```bash
# Upload a module
curl -X PUT \
  "https://registry.example.com/v1/modules/myorg/vpc/aws/1.0.0" \
  -H "Authorization: Bearer your-uploader-token" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @module.tar.gz

# Create a downloader token
curl -X POST \
  "https://registry.example.com/v1/tokens" \
  -H "Authorization: Bearer your-master-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-reader", "permission": "downloader"}'
```


## 💡 Examples

- [Basic](examples/basic) — Minimal deployment with required variables only
- [Proxy Mode](examples/proxy-mode) — Portal with proxy mode enabled and allow/deny lists
- [Complete](examples/complete) — All optional features configured

## 📥 Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| `domain_name` | Custom domain name for the registry (e.g., `registry.example.com`). Must be a valid DNS hostname. This domain is used for the API Gateway custom domain and service discovery endpoint. | `string` | — | yes |
| `certificate_arn` | ARN of a pre-existing ACM certificate covering the custom domain. Must be a valid ACM certificate ARN (e.g., `arn:aws:acm:us-east-1:123456789012:certificate/abcd1234-ef56-gh78-ij90-klmnopqrstuv`). | `string` | — | yes |
| `proxy_enabled` | Enable proxy fallback to the public Terraform Registry when a module is not found locally. When set to false (the default), only modules uploaded directly to Portal are served. | `bool` | `false` | no |
| `proxy_allow_list` | Prefix expressions for modules eligible for proxying (e.g., `["hashicorp/", "myorg/vpc"]`). When the list is empty and proxy is enabled, all modules are eligible for proxying. Each entry is matched as a prefix against the module's namespace/name path. | `list(string)` | `[]` | no |
| `proxy_deny_list` | Prefix expressions for modules excluded from proxying (e.g., `["internal/", "private/secrets"]`). Deny list takes precedence over allow list. Each entry is matched as a prefix against the module's namespace/name path. | `list(string)` | `[]` | no |
| `s3_bucket_name` | Override the default S3 bucket name for storing module packages. When empty (the default), the bucket is named `portal-modules-{account_id}` using the current AWS account ID. | `string` | `""` | no |
| `token_table_name` | Name of the DynamoDB table for storing API tokens. Defaults to `portal-tokens`. Change this if you need to avoid naming conflicts with existing DynamoDB tables in your account. | `string` | `"portal-tokens"` | no |
| `master_token_secret_name` | Name of the Secrets Manager secret for the master token. Defaults to `prtl-master-token`. The master token is used for administrative operations such as creating and revoking API tokens. | `string` | `"prtl-master-token"` | no |

## 📤 Outputs

| Name | Description |
|------|-------------|
| `api_endpoint` | API Gateway stage invoke URL |
| `api_id` | API Gateway REST API ID |
| `s3_bucket_name` | Name of the S3 modules bucket |
| `s3_bucket_arn` | ARN of the S3 modules bucket |
| `dynamodb_table_name` | Name of the DynamoDB tokens table |
| `master_token_secret_arn` | ARN of the Secrets Manager master token secret |
| `api_gateway_domain_name` | The execute-api regional hostname of the REST API |
| `custom_domain_regional_domain_name` | Regional domain name of the custom domain for DNS CNAME/alias targeting |
| `custom_domain_regional_zone_id` | Regional hosted zone ID of the custom domain for Route 53 alias targeting |

## 💰 Cost

Portal is fully serverless, so you only pay for what you use. With low to moderate usage (a small team uploading and downloading modules during CI/CD), expect costs well under $1/month. The main cost drivers are:

| Service | What Portal uses it for | Pricing model |
|---------|------------------------|---------------|
| API Gateway | REST API for all module and token operations | Per-request ($3.50 per million requests) |
| Lambda | Request handling and authorization (two functions) | Per-request + duration (1M free requests/month) |
| S3 | Module archive storage | Storage ($0.023/GB/month) + requests |
| DynamoDB | Token storage (on-demand) | Per-request (25 GB + 25 WCU/RCU free tier) |
| Secrets Manager | Master token storage (one secret) | $0.40/secret/month + $0.05 per 10K API calls |

At rest with no traffic, the only fixed cost is the single Secrets Manager secret (~$0.40/month). Everything else scales to zero. For a team running a few hundred `terraform init` calls per day, total cost typically stays under $5/month.

## 📄 License

See [LICENSE](LICENSE) for details.
