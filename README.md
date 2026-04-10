# AWS Serverless Terraform Module Registry

[![CI](https://github.com/sebacaccaro/terraform-aws-serverless-module-registry/actions/workflows/ci.yml/badge.svg)](https://github.com/sebacaccaro/terraform-aws-serverless-module-registry/actions/workflows/ci.yml)
[![Release](https://github.com/sebacaccaro/terraform-aws-serverless-module-registry/actions/workflows/release.yml/badge.svg)](https://github.com/sebacaccaro/terraform-aws-serverless-module-registry/actions/workflows/release.yml)
[![GitHub release](https://img.shields.io/github/v/release/sebacaccaro/terraform-aws-serverless-module-registry?sort=semver)](https://github.com/sebacaccaro/terraform-aws-serverless-module-registry/releases/latest)
[![License](https://img.shields.io/github/license/sebacaccaro/terraform-aws-serverless-module-registry)](LICENSE)

A private, fully serverless Terraform module registry for AWS. It lets you host, distribute, and manage Terraform modules behind your own domain with token-based authentication. It can also proxy requests to the public Terraform Registry and pin specific module versions locally for reproducible, air-gap-friendly builds.

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
module "registry" {
  source = "your-registry/se-registry/aws"

  domain_name     = "registry.example.com"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
}
```

After applying, create a DNS CNAME or alias record pointing your `domain_name` to the `custom_domain_regional_domain_name` output.

## 📖 Use Cases

### 🔒 Private Registry

#### Configuring Terraform CLI Credentials

To authenticate Terraform CLI with your registry, add a credentials block to your `~/.terraformrc` (Linux/macOS) or `%APPDATA%/terraform.rc` (Windows) file:

```hcl
credentials "registry.example.com" {
  token = "your-api-token"
}
```

Replace `registry.example.com` with your custom domain and `your-api-token` with a valid downloader or uploader token.

Alternatively you can export the `TF_TOKEN_` environment variable. The variable name is built from the hostname by replacing dots with underscores and hyphens with double underscores. For example, if your registry domain is `my-registry.example.com`:

```bash
export TF_TOKEN_my__registry_example_com="your-api-token"
```

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

Use your custom domain as the module source in Terraform configurations:

```hcl
module "vpc" {
  source  = "registry.example.com/myorg/vpc/aws"
  version = "1.0.0"
}
```

Terraform CLI uses the `/.well-known/terraform.json` service discovery endpoint to locate the module API automatically.

#### Token Permission Model

The registry uses three token tiers. Each tier inherits the permissions of the ones below it:

| Token Type | Download / List Modules | Upload Modules | Pin Modules | Manage Tokens |
| ---------- | :---------------------: | :------------: | :---------: | :-----------: |
| master     |            ✓            |       ✓        |      ✓      |       ✓       |
| uploader   |            ✓            |       ✓        |             |               |
| downloader |            ✓            |                |             |               |

**master** — Auto-generated at deploy time and stored in AWS Secrets Manager (see the `master_token_secret_name` input). This is the only token that can create/list/revoke other tokens and pin public modules. Treat it like a root credential: use it for initial setup and administrative tasks, not for day-to-day operations.

**uploader** — Can push new module versions (`PUT /v1/modules/...`) and also download/list them. Ideal for CI/CD pipelines that publish modules after a successful build.

**downloader** — Read-only access: list available versions and download module archives. This is the token you should put in `.terraformrc` or `TF_TOKEN_` environment variables for developers and for pipelines that only consume modules.

#### Managing Tokens

All token management operations require the master token.

Create a token:

```bash
curl -X POST \
  "https://registry.example.com/v1/tokens" \
  -H "Authorization: Bearer your-master-token" \
  -H "Content-Type: application/json" \
  -d '{"name": "ci-downloader", "permission": "downloader"}'
```

The response includes the token value. Store it securely — it cannot be retrieved again.

List existing tokens (token values are not returned):

```bash
curl "https://registry.example.com/v1/tokens" \
  -H "Authorization: Bearer your-master-token"
```

Revoke a token by name:

```bash
curl -X DELETE \
  "https://registry.example.com/v1/tokens/ci-downloader" \
  -H "Authorization: Bearer your-master-token"
```

### 🔀 Proxy Mode

The registry can transparently proxy module download requests to the public Terraform Registry when a module is not found locally. This lets you use your private registry as a single source for both private and public modules.

Enable proxy mode by setting `proxy_enabled = true`:

```hcl
module "registry" {
  source = "your-registry/se-registry/aws"

  domain_name     = "registry.example.com"
  certificate_arn = "arn:aws:acm:us-east-1:123456789012:certificate/aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

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

Pinning a module version downloads the archive from the public registry once and stores it in your S3 bucket. From that point on, the registry serves the local copy directly — it stops proxying that module version entirely. Your Terraform runs use the exact artifact you pinned, regardless of whether the public registry is available or whether the upstream maintainer has yanked or replaced the release.

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

All endpoints (except service discovery) require a `Authorization: Bearer <token>` header. The complete OpenAPI specification is available in [`openapi.json`](openapi.json).

Module paths use the format `{namespace}/{name}/{system}` where each segment is 1–64 lowercase alphanumeric characters, hyphens, or underscores. Versions must be valid semver (`X.Y.Z`).

### Service Discovery

| | |
|---|---|
| `GET /.well-known/terraform.json` | No auth required |

Returns the service discovery document that Terraform CLI uses to locate the module API. You don't call this directly — Terraform handles it automatically when you use your registry domain as a module source.

### Modules

| Endpoint | Method | Required Token | Description |
|---|---|---|---|
| `/v1/modules/{ns}/{name}/{system}/versions` | `GET` | downloader+ | List all versions of a module |
| `/v1/modules/{ns}/{name}/{system}/{version}/download` | `GET` | downloader+ | Download a module archive |
| `/v1/modules/{ns}/{name}/{system}/{version}` | `PUT` | uploader+ | Upload a new module version |

**Upload a module version:**

```bash
curl -X PUT \
  "https://registry.example.com/v1/modules/myorg/vpc/aws/1.0.0" \
  -H "Authorization: Bearer your-uploader-token" \
  -H "Content-Type: application/octet-stream" \
  --data-binary @module.tar.gz
```

Returns `201` on success, `409` if the version already exists. The body must be a `.tar.gz` or `.zip` archive.

**List versions:**

```bash
curl "https://registry.example.com/v1/modules/myorg/vpc/aws/versions" \
  -H "Authorization: Bearer your-downloader-token"
```

**Download a module:**

```bash
curl -I "https://registry.example.com/v1/modules/myorg/vpc/aws/1.0.0/download" \
  -H "Authorization: Bearer your-downloader-token"
```

Returns `204` with an `X-Terraform-Get` header containing a presigned S3 URL. Terraform CLI follows this automatically — you only need this for manual downloads.

### Tokens

| Endpoint | Method | Required Token | Description |
|---|---|---|---|
| `/v1/tokens` | `POST` | master | Create a new token |
| `/v1/tokens` | `GET` | master | List all tokens (values are not returned) |
| `/v1/tokens/{token_name}` | `DELETE` | master | Revoke a token |

See [Managing Tokens](#managing-tokens) for examples.

### Pins

| Endpoint | Method | Required Token | Description |
|---|---|---|---|
| `/v1/pins/{ns}/{name}/{system}/{version}` | `POST` | master | Pin a public module version locally |

```bash
curl -X POST \
  "https://registry.example.com/v1/pins/hashicorp/consul/aws/0.12.0" \
  -H "Authorization: Bearer your-master-token"
```

Returns `201` on success, `404` if the module doesn't exist on the public registry, `409` if already pinned locally. Requires proxy mode to be enabled.

## 💡 Examples

- [Basic](examples/basic) — Minimal deployment with required variables only
- [Proxy Mode](examples/proxy-mode) — Proxy mode enabled with allow/deny lists
- [Complete](examples/complete) — All optional features configured

## 📥 Inputs

| Name                       | Description                                                                                                                                                                                                                                                 | Type           | Default                      | Required |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | ---------------------------- | :------: |
| `domain_name`              | Custom domain name for the registry (e.g., `registry.example.com`). Must be a valid DNS hostname. This domain is used for the API Gateway custom domain and service discovery endpoint.                                                                     | `string`       | —                            |   yes    |
| `certificate_arn`          | ARN of a pre-existing ACM certificate covering the custom domain. Must be a valid ACM certificate ARN (e.g., `arn:aws:acm:us-east-1:123456789012:certificate/abcd1234-ef56-gh78-ij90-klmnopqrstuv`).                                                        | `string`       | —                            |   yes    |
| `proxy_enabled`            | Enable proxy fallback to the public Terraform Registry when a module is not found locally. When set to false (the default), only modules uploaded directly are served.                                                                                      | `bool`         | `false`                      |    no    |
| `proxy_allow_list`         | Prefix expressions for modules eligible for proxying (e.g., `["hashicorp/", "myorg/vpc"]`). When the list is empty and proxy is enabled, all modules are eligible for proxying. Each entry is matched as a prefix against the module's namespace/name path. | `list(string)` | `[]`                         |    no    |
| `proxy_deny_list`          | Prefix expressions for modules excluded from proxying (e.g., `["internal/", "private/secrets"]`). Deny list takes precedence over allow list. Each entry is matched as a prefix against the module's namespace/name path.                                   | `list(string)` | `[]`                         |    no    |
| `s3_bucket_name`           | Override the default S3 bucket name for storing module packages. When empty (the default), the bucket is named `se-registry-modules-{account_id}` using the current AWS account ID.                                                                         | `string`       | `""`                         |    no    |
| `token_table_name`         | Name of the DynamoDB table for storing API tokens. Defaults to `se-registry-tokens`. Change this if you need to avoid naming conflicts with existing DynamoDB tables in your account.                                                                       | `string`       | `"se-registry-tokens"`       |    no    |
| `master_token_secret_name` | Name of the Secrets Manager secret for the master token. Defaults to `se-registry-master-token`. The master token is used for administrative operations such as creating and revoking API tokens.                                                           | `string`       | `"se-registry-master-token"` |    no    |

## 📤 Outputs

| Name                                 | Description                                                               |
| ------------------------------------ | ------------------------------------------------------------------------- |
| `api_endpoint`                       | API Gateway stage invoke URL                                              |
| `api_id`                             | API Gateway REST API ID                                                   |
| `s3_bucket_name`                     | Name of the S3 modules bucket                                             |
| `s3_bucket_arn`                      | ARN of the S3 modules bucket                                              |
| `dynamodb_table_name`                | Name of the DynamoDB tokens table                                         |
| `master_token_secret_arn`            | ARN of the Secrets Manager master token secret                            |
| `api_gateway_domain_name`            | The execute-api regional hostname of the REST API                         |
| `custom_domain_regional_domain_name` | Regional domain name of the custom domain for DNS CNAME/alias targeting   |
| `custom_domain_regional_zone_id`     | Regional hosted zone ID of the custom domain for Route 53 alias targeting |

## 💰 Cost

The registry is fully serverless, so you only pay for what you use. With low to moderate usage (a small team uploading and downloading modules during CI/CD), expect costs well under $1/month. The main cost drivers are:

| Service         | What it's used for                                 | Pricing model                                   |
| --------------- | -------------------------------------------------- | ----------------------------------------------- |
| API Gateway     | REST API for all module and token operations       | Per-request ($3.50 per million requests)        |
| Lambda          | Request handling and authorization (two functions) | Per-request + duration (1M free requests/month) |
| S3              | Module archive storage                             | Storage ($0.023/GB/month) + requests            |
| DynamoDB        | Token storage (on-demand)                          | Per-request (25 GB + 25 WCU/RCU free tier)      |
| Secrets Manager | Master token storage (one secret)                  | $0.40/secret/month + $0.05 per 10K API calls    |

At rest with no traffic, the only fixed cost is the single Secrets Manager secret (~$0.40/month). Everything else scales to zero. For a team running a few hundred `terraform init` calls per day, total cost typically stays under $5/month.

## 📄 License

See [LICENSE](LICENSE) for details.
