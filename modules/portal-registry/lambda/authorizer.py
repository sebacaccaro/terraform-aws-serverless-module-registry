"""Lambda authorizer for bearer token authentication.

Validates bearer tokens against the master token (Secrets Manager) and
DynamoDB Token_Table. Returns an IAM policy with permission and is_master
in the authorizer context.
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Module-level cache — persists across invocations in the same Lambda container
_master_token_cache = None


def _get_master_token():
    """Retrieve the master token from Secrets Manager, caching for container lifetime."""
    global _master_token_cache
    if _master_token_cache is None:
        sm = boto3.client("secretsmanager")
        secret_arn = os.environ["MASTER_TOKEN_SECRET_ARN"]
        resp = sm.get_secret_value(SecretId=secret_arn)
        _master_token_cache = resp["SecretString"]
    return _master_token_cache


def _build_policy(method_arn, effect, context=None):
    """Build an IAM policy document for API Gateway authorizer response."""
    # Extract the base ARN (everything up to the method) for a wildcard resource
    arn_parts = method_arn.split(":")
    api_gw_arn = ":".join(arn_parts[:5])
    rest_api_part = arn_parts[5]
    # Use wildcard to cover all methods/resources
    resource_arn = f"{api_gw_arn}:{rest_api_part.split('/')[0]}/*"

    policy = {
        "principalId": "user",
        "policyDocument": {
            "Version": "2012-10-17",
            "Statement": [
                {
                    "Action": "execute-api:Invoke",
                    "Effect": effect,
                    "Resource": resource_arn,
                }
            ],
        },
    }
    if context:
        policy["context"] = context
    return policy


def _extract_token(authorization_token):
    """Extract the bearer token from the authorizationToken field.

    Handles both 'Bearer <token>' and raw '<token>' formats.
    Returns None if the value is empty or missing.
    """
    if not authorization_token:
        return None
    token = authorization_token
    if token.lower().startswith("bearer "):
        token = token[7:]
    return token.strip() or None


def handler(event, context):
    """Authorizer Lambda entry point. Validates bearer tokens.

    Checks the master token from Secrets Manager first (cached), then
    falls back to DynamoDB Token_Table lookup. Returns Allow policy with
    permission context on success, Deny policy on failure.
    """
    method_arn = event.get("methodArn", "")

    try:
        token = _extract_token(event.get("authorizationToken", ""))
        if not token:
            logger.info("Missing or empty authorization token")
            return _build_policy(method_arn, "Deny")

        # Check master token first
        try:
            master_token = _get_master_token()
            if token == master_token:
                logger.info("Master token authenticated")
                return _build_policy(method_arn, "Allow", {
                    "permission": "master",
                    "is_master": "true",
                })
        except Exception as e:
            logger.error("Error retrieving master token: %s", str(e))
            # Fall through to DynamoDB lookup

        # Look up token in DynamoDB
        try:
            ddb = boto3.resource("dynamodb")
            table = ddb.Table(os.environ["TOKEN_TABLE_NAME"])
            resp = table.get_item(Key={"token_value": token})

            if "Item" in resp:
                item = resp["Item"]
                permission = item.get("permission", "downloader")
                logger.info("Token authenticated with permission: %s", permission)
                return _build_policy(method_arn, "Allow", {
                    "permission": permission,
                    "is_master": "false",
                })
        except Exception as e:
            logger.error("Error looking up token in DynamoDB: %s", str(e))

        # Token not found
        logger.info("Unknown token — denying access")
        return _build_policy(method_arn, "Deny")

    except Exception as e:
        logger.exception("Unhandled authorizer error: %s", str(e))
        return _build_policy(method_arn, "Deny")
