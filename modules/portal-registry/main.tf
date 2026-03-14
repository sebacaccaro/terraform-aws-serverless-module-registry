# =============================================================================
# S3, API Gateway Base, and IAM Resources (from api-gateway-base.tf)
# =============================================================================

data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "modules" {
  bucket = var.s3_bucket_name != "" ? var.s3_bucket_name : "portal-modules-${data.aws_caller_identity.current.account_id}"
}

resource "aws_s3_bucket_versioning" "modules" {
  bucket = aws_s3_bucket.modules.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_api_gateway_rest_api" "main" {
  name = "portal-api"

  binary_media_types = [
    "application/octet-stream",
    "application/zip",
  ]
}

resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  triggers = {
    redeployment = sha1(jsonencode([
      filesha1("${path.module}/main.tf"),
      aws_api_gateway_resource.v1.id,
      aws_api_gateway_resource.modules.id,
      aws_api_gateway_resource.modules_proxy.id,
      aws_api_gateway_method.modules_any.id,
      aws_api_gateway_integration.modules.id,
      aws_api_gateway_resource.tokens.id,
      aws_api_gateway_method.tokens_post.id,
      aws_api_gateway_integration.tokens_post.id,
      aws_api_gateway_method.tokens_get.id,
      aws_api_gateway_integration.tokens_get.id,
      aws_api_gateway_resource.token_name.id,
      aws_api_gateway_method.token_delete.id,
      aws_api_gateway_integration.token_delete.id,
      aws_api_gateway_resource.well_known.id,
      aws_api_gateway_resource.well_known_proxy.id,
      aws_api_gateway_method.well_known_get.id,
      aws_api_gateway_integration.well_known_s3.id,
      aws_api_gateway_authorizer.token.id,
      aws_api_gateway_resource.pins.id,
      aws_api_gateway_resource.pins_proxy.id,
      aws_api_gateway_method.pins_post.id,
      aws_api_gateway_integration.pins_post.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "main" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  deployment_id = aws_api_gateway_deployment.main.id
  stage_name    = "prod"
}

resource "aws_iam_role" "apigw" {
  name = "portal-apigw-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "apigw_s3" {
  role = aws_iam_role.apigw.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "s3:GetObject"
      Resource = "${aws_s3_bucket.modules.arn}/*"
    }]
  })
}

resource "aws_iam_role_policy" "apigw_lambda" {
  role = aws_iam_role.apigw.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.authorizer.arn
    }]
  })
}

# =============================================================================
# Auth Resources (from auth.tf)
# =============================================================================

## DynamoDB Token Table

resource "aws_dynamodb_table" "tokens" {
  name         = var.token_table_name
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "token_value"

  attribute {
    name = "token_value"
    type = "S"
  }

  attribute {
    name = "token_name"
    type = "S"
  }

  global_secondary_index {
    name            = "token_name-index"
    projection_type = "ALL"

    key_schema {
      attribute_name = "token_name"
      key_type       = "HASH"
    }
  }
}

## Secrets Manager — Master Token

resource "random_password" "master_token" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "master_token" {
  name = var.master_token_secret_name
}

resource "aws_secretsmanager_secret_version" "master_token" {
  secret_id     = aws_secretsmanager_secret.master_token.id
  secret_string = random_password.master_token.result
}

## Lambda Authorizer Function

data "archive_file" "authorizer" {
  type        = "zip"
  source_file = "${path.module}/lambda/authorizer.py"
  output_path = "${path.module}/authorizer.zip"
}

resource "aws_lambda_function" "authorizer" {
  filename         = data.archive_file.authorizer.output_path
  function_name    = "portal-authorizer"
  role             = aws_iam_role.authorizer.arn
  handler          = "authorizer.handler"
  runtime          = "python3.12"
  source_code_hash = data.archive_file.authorizer.output_base64sha256
  timeout          = 10

  environment {
    variables = {
      TOKEN_TABLE_NAME       = aws_dynamodb_table.tokens.name
      MASTER_TOKEN_SECRET_ARN = aws_secretsmanager_secret.master_token.arn
    }
  }
}

resource "aws_iam_role" "authorizer" {
  name = "portal-authorizer-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "authorizer_basic" {
  role       = aws_iam_role.authorizer.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "authorizer_access" {
  role = aws_iam_role.authorizer.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "dynamodb:GetItem"
        Resource = aws_dynamodb_table.tokens.arn
      },
      {
        Effect   = "Allow"
        Action   = "secretsmanager:GetSecretValue"
        Resource = aws_secretsmanager_secret.master_token.arn
      }
    ]
  })
}

## API Gateway Authorizer

resource "aws_api_gateway_authorizer" "token" {
  name                             = "portal-token-authorizer"
  rest_api_id                      = aws_api_gateway_rest_api.main.id
  type                             = "TOKEN"
  authorizer_uri                   = aws_lambda_function.authorizer.invoke_arn
  authorizer_credentials           = aws_iam_role.apigw.arn
  identity_source                  = "method.request.header.Authorization"
  authorizer_result_ttl_in_seconds = 0
}

resource "aws_lambda_permission" "authorizer" {
  statement_id  = "AllowAPIGatewayAuthorizer"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*"
}

# =============================================================================
# Endpoint Resources (from endpoints.tf)
# =============================================================================

## Python Lambda Handler

data "archive_file" "lambda" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/lambda.zip"
  excludes    = ["tests", "tests/**", "__pycache__", "__pycache__/**", ".pytest_cache", ".pytest_cache/**", ".hypothesis", ".hypothesis/**"]
}

resource "aws_lambda_function" "api" {
  filename         = data.archive_file.lambda.output_path
  function_name    = "portal-api-handler"
  role             = aws_iam_role.lambda.arn
  handler          = "handler.handler"
  runtime          = "python3.12"
  source_code_hash = data.archive_file.lambda.output_base64sha256
  timeout          = 30

  environment {
    variables = {
      MODULES_BUCKET          = aws_s3_bucket.modules.id
      PROXY_ENABLED           = tostring(var.proxy_enabled)
      PROXY_ALLOW_LIST        = join(",", var.proxy_allow_list)
      PROXY_DENY_LIST         = join(",", var.proxy_deny_list)
      TOKEN_TABLE_NAME        = aws_dynamodb_table.tokens.name
      MASTER_TOKEN_SECRET_ARN = aws_secretsmanager_secret.master_token.arn
    }
  }
}

resource "aws_iam_role" "lambda" {
  name = "portal-lambda-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "lambda" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy" "lambda_s3" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:GetObject",
        "s3:PutObject",
      ]
      Resource = "${aws_s3_bucket.modules.arn}/*"
    },
    {
      Effect   = "Allow"
      Action   = "s3:ListBucket"
      Resource = aws_s3_bucket.modules.arn
    }]
  })
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:PutItem",
        "dynamodb:Scan",
        "dynamodb:DeleteItem",
        "dynamodb:Query",
      ]
      Resource = [
        aws_dynamodb_table.tokens.arn,
        "${aws_dynamodb_table.tokens.arn}/index/*",
      ]
    }]
  })
}

## /v1/modules/{proxy+} — catch-all for module routes

resource "aws_api_gateway_resource" "v1" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "v1"
}

resource "aws_api_gateway_resource" "modules" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "modules"
}

resource "aws_api_gateway_resource" "modules_proxy" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.modules.id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "modules_any" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.modules_proxy.id
  http_method   = "ANY"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.token.id
}

resource "aws_api_gateway_integration" "modules" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.modules_proxy.id
  http_method             = aws_api_gateway_method.modules_any.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.api.invoke_arn
}

## /v1/tokens — POST and GET

resource "aws_api_gateway_resource" "tokens" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "tokens"
}

resource "aws_api_gateway_method" "tokens_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.tokens.id
  http_method   = "POST"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.token.id
}

resource "aws_api_gateway_integration" "tokens_post" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.tokens.id
  http_method             = aws_api_gateway_method.tokens_post.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.api.invoke_arn
}

resource "aws_api_gateway_method" "tokens_get" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.tokens.id
  http_method   = "GET"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.token.id
}

resource "aws_api_gateway_integration" "tokens_get" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.tokens.id
  http_method             = aws_api_gateway_method.tokens_get.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.api.invoke_arn
}

## /v1/tokens/{token_name} — DELETE

resource "aws_api_gateway_resource" "token_name" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.tokens.id
  path_part   = "{token_name}"
}

resource "aws_api_gateway_method" "token_delete" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.token_name.id
  http_method   = "DELETE"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.token.id
}

resource "aws_api_gateway_integration" "token_delete" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.token_name.id
  http_method             = aws_api_gateway_method.token_delete.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.api.invoke_arn
}

## /v1/pins/{proxy+} — cache module versions from public registry

resource "aws_api_gateway_resource" "pins" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "pins"
}

resource "aws_api_gateway_resource" "pins_proxy" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.pins.id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "pins_post" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.pins_proxy.id
  http_method   = "POST"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.token.id
}

resource "aws_api_gateway_integration" "pins_post" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.pins_proxy.id
  http_method             = aws_api_gateway_method.pins_post.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.api.invoke_arn
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*"
}


## Service Discovery — /.well-known/terraform.json

resource "aws_api_gateway_resource" "well_known" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = ".well-known"
}

resource "aws_api_gateway_resource" "well_known_proxy" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_resource.well_known.id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "well_known_get" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.well_known_proxy.id
  http_method   = "GET"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.token.id

  request_parameters = {
    "method.request.path.proxy" = true
  }
}

data "aws_region" "current" {}

resource "aws_api_gateway_integration" "well_known_s3" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.well_known_proxy.id
  http_method             = aws_api_gateway_method.well_known_get.http_method
  type                    = "AWS"
  integration_http_method = "GET"
  uri                     = "arn:aws:apigateway:${data.aws_region.current.id}:s3:path/{bucket}/.well-known/{key}"
  credentials             = aws_iam_role.apigw.arn

  request_parameters = {
    "integration.request.path.bucket" = "'${aws_s3_bucket.modules.id}'"
    "integration.request.path.key"    = "method.request.path.proxy"
  }
}

resource "aws_api_gateway_method_response" "well_known_200" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  resource_id = aws_api_gateway_resource.well_known_proxy.id
  http_method = aws_api_gateway_method.well_known_get.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Content-Type" = true
  }
}

resource "aws_api_gateway_integration_response" "well_known_200" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  resource_id = aws_api_gateway_resource.well_known_proxy.id
  http_method = aws_api_gateway_method.well_known_get.http_method
  status_code = aws_api_gateway_method_response.well_known_200.status_code

  response_parameters = {
    "method.response.header.Content-Type" = "integration.response.header.Content-Type"
  }

  depends_on = [aws_api_gateway_integration.well_known_s3]
}

resource "aws_s3_object" "terraform_json" {
  bucket       = aws_s3_bucket.modules.id
  key          = ".well-known/terraform.json"
  content      = jsonencode({ "modules.v1" : "https://${var.domain_name}/v1/modules/" })
  content_type = "application/json"
}

# =============================================================================
# Custom Domain Resources
# =============================================================================

resource "aws_api_gateway_domain_name" "custom" {
  domain_name              = var.domain_name
  regional_certificate_arn = var.certificate_arn
  endpoint_configuration {
    types = ["REGIONAL"]
  }
}

resource "aws_api_gateway_base_path_mapping" "custom" {
  api_id      = aws_api_gateway_rest_api.main.id
  stage_name  = aws_api_gateway_stage.main.stage_name
  domain_name = aws_api_gateway_domain_name.custom.domain_name
}
