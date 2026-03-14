"""Main Lambda handler with request routing."""

import json
import logging
import os
import re

import s3_client
import token_manager
from proxy import should_proxy, proxy_request, UpstreamNotFoundError, UpstreamError, fetch_from_public_registry
from validators import ValidationError, validate_path_param, validate_semver

logger = logging.getLogger()
logger.setLevel(logging.INFO)

MODULES_BUCKET = os.environ.get("MODULES_BUCKET", "")
TOKEN_TABLE_NAME = os.environ.get("TOKEN_TABLE_NAME", "")


def _get_proxy_config():
    """Read proxy configuration from environment variables."""
    enabled = os.environ.get("PROXY_ENABLED", "false").lower() == "true"
    allow_raw = os.environ.get("PROXY_ALLOW_LIST", "")
    deny_raw = os.environ.get("PROXY_DENY_LIST", "")
    return {
        "enabled": enabled,
        "allow_list": [p.strip() for p in allow_raw.split(",") if p.strip()] if allow_raw else [],
        "deny_list": [p.strip() for p in deny_raw.split(",") if p.strip()] if deny_raw else [],
    }


def _json_response(status_code, body, extra_headers=None):
    """Build an API Gateway proxy response dict."""
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status_code,
        "headers": headers,
        "body": json.dumps(body),
    }


def _error_response(status_code, error_code, message):
    """Build a JSON error response."""
    return _json_response(status_code, {"error": error_code, "message": message})


def _s3_key(namespace, name, system, version):
    """Build the S3 key for a module archive."""
    return f"{namespace}/{name}/{system}/{version}/{name}-{system}-{version}.zip"


def _validate_module_params(params):
    """Validate namespace, name, and system path params. Raises ValidationError."""
    validate_path_param("namespace", params["namespace"])
    validate_path_param("name", params["name"])
    validate_path_param("system", params["system"])


# --- Route handlers ---


def list_versions(event, params):
    """GET /v1/modules/{namespace}/{name}/{system}/versions"""
    _validate_module_params(params)
    prefix = f"{params['namespace']}/{params['name']}/{params['system']}/"
    versions = s3_client.list_versions(MODULES_BUCKET, prefix)
    if not versions:
        # Try proxy fallback
        config = _get_proxy_config()
        if config["enabled"] and should_proxy(params["namespace"], params["name"], config):
            path = event.get("path", "")
            return proxy_request(path)
        return _error_response(
            404,
            "not_found",
            f"No versions found for module {params['namespace']}/{params['name']}/{params['system']}",
        )
    return _json_response(
        200,
        {"modules": [{"versions": [{"version": v} for v in versions]}]},
    )


def download_version(event, params):
    """GET /v1/modules/{namespace}/{name}/{system}/{version}/download"""
    _validate_module_params(params)
    validate_semver(params["version"])
    key = _s3_key(params["namespace"], params["name"], params["system"], params["version"])
    if not s3_client.head_object(MODULES_BUCKET, key):
        # Check if any local versions exist for this module (proxy blocking)
        prefix = f"{params['namespace']}/{params['name']}/{params['system']}/"
        if s3_client.has_local_versions(MODULES_BUCKET, prefix):
            # Module is pinned — requested version not available locally
            return _error_response(
                404,
                "not_found",
                f"Version {params['version']} of module {params['namespace']}/{params['name']}/{params['system']} not found",
            )
        # No local versions at all — try proxy fallback
        config = _get_proxy_config()
        if config["enabled"] and should_proxy(params["namespace"], params["name"], config):
            path = event.get("path", "")
            return proxy_request(path)
        return _error_response(
            404,
            "not_found",
            f"Version {params['version']} of module {params['namespace']}/{params['name']}/{params['system']} not found",
        )
    url = s3_client.get_presigned_url(MODULES_BUCKET, key)
    return {
        "statusCode": 204,
        "headers": {"X-Terraform-Get": url},
        "body": "",
    }


def upload_version(event, params):
    """PUT /v1/modules/{namespace}/{name}/{system}/{version}"""
    _validate_module_params(params)
    validate_semver(params["version"])

    key = _s3_key(params["namespace"], params["name"], params["system"], params["version"])
    if s3_client.head_object(MODULES_BUCKET, key):
        return _error_response(
            409,
            "conflict",
            f"Version {params['version']} of module {params['namespace']}/{params['name']}/{params['system']} already exists",
        )

    body = event.get("body", b"") or b""
    if isinstance(body, str):
        import base64
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body)
        else:
            body = body.encode("utf-8")

    s3_client.put_object(MODULES_BUCKET, key, body)
    return _json_response(201, {
        "namespace": params["namespace"],
        "name": params["name"],
        "system": params["system"],
        "version": params["version"],
    })

def cache_version(event, params):
    """POST /v1/pins/{namespace}/{name}/{system}/{version}"""
    _validate_module_params(params)
    validate_semver(params["version"])

    namespace = params["namespace"]
    name = params["name"]
    system = params["system"]
    version = params["version"]

    key = _s3_key(namespace, name, system, version)
    if s3_client.head_object(MODULES_BUCKET, key):
        return _error_response(
            409,
            "conflict",
            f"Version {version} of module {namespace}/{name}/{system} already exists locally",
        )

    try:
        archive = fetch_from_public_registry(namespace, name, system, version)
    except UpstreamNotFoundError:
        return _error_response(
            404,
            "not_found",
            f"Module {namespace}/{name}/{system} version {version} not found on public registry",
        )
    except UpstreamError as e:
        return _error_response(
            502,
            "bad_gateway",
            f"Failed to fetch from public registry: {e}",
        )

    s3_client.put_object(MODULES_BUCKET, key, archive)
    return _json_response(201, {
        "namespace": namespace,
        "name": name,
        "system": system,
        "version": version,
    })



def create_token_handler(event, params):
    """POST /v1/tokens"""
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    name = body.get("name")
    if not name or not isinstance(name, str) or not name.strip():
        return _error_response(400, "invalid_parameter", "Token name is required and must be a non-empty string")

    permission = body.get("permission")
    if permission not in ("uploader", "downloader"):
        return _error_response(400, "invalid_permission", "Permission must be 'uploader' or 'downloader'")

    existing = token_manager.get_token_by_name(TOKEN_TABLE_NAME, name)
    if existing:
        return _error_response(409, "conflict", f"A token with name '{name}' already exists")

    item = token_manager.create_token(TOKEN_TABLE_NAME, name, permission)
    return _json_response(201, item)


def list_tokens_handler(event, params):
    """GET /v1/tokens"""
    items = token_manager.list_tokens(TOKEN_TABLE_NAME)
    return _json_response(200, {"tokens": items})


def delete_token_handler(event, params):
    """DELETE /v1/tokens/{token_name}"""
    token_name = params["token_name"]
    existing = token_manager.get_token_by_name(TOKEN_TABLE_NAME, token_name)
    if not existing:
        return _error_response(404, "not_found", f"Token '{token_name}' not found")

    token_manager.delete_token(TOKEN_TABLE_NAME, token_name)
    return _json_response(200, {"message": f"Token '{token_name}' deleted"})


# --- Permission levels ---
# Each route specifies the minimum permission required.
# "downloader" = GET on module endpoints (downloader, uploader, master all allowed)
# "uploader" = PUT on module endpoints (uploader and master allowed)
# "master" = token management (master only)
PERMISSION_HIERARCHY = {"master": 3, "uploader": 2, "downloader": 1}


def _check_permission(event, required_permission):
    """Check if the caller has sufficient permission for the route.

    Returns None if allowed, or an error response dict if denied.
    """
    context = event.get("requestContext", {}).get("authorizer", {})
    caller_permission = context.get("permission", "")
    caller_level = PERMISSION_HIERARCHY.get(caller_permission, 0)
    required_level = PERMISSION_HIERARCHY.get(required_permission, 0)
    if caller_level < required_level:
        if required_permission == "master":
            return _error_response(403, "forbidden", "Only the master token can manage tokens")
        return _error_response(403, "forbidden", "Insufficient permissions for this operation")
    return None


# --- Route table ---
# Each entry: (method, pattern, handler, required_permission)

ROUTES = [
    ("GET", re.compile(r"^/v1/modules/(?P<namespace>[^/]+)/(?P<name>[^/]+)/(?P<system>[^/]+)/versions$"), list_versions, "downloader"),
    ("GET", re.compile(r"^/v1/modules/(?P<namespace>[^/]+)/(?P<name>[^/]+)/(?P<system>[^/]+)/(?P<version>[^/]+)/download$"), download_version, "downloader"),
    ("PUT", re.compile(r"^/v1/modules/(?P<namespace>[^/]+)/(?P<name>[^/]+)/(?P<system>[^/]+)/(?P<version>[^/]+)$"), upload_version, "uploader"),
    ("POST", re.compile(r"^/v1/pins/(?P<namespace>[^/]+)/(?P<name>[^/]+)/(?P<system>[^/]+)/(?P<version>[^/]+)$"), cache_version, "master"),
    ("POST", re.compile(r"^/v1/tokens$"), create_token_handler, "master"),
    ("GET", re.compile(r"^/v1/tokens$"), list_tokens_handler, "master"),
    ("DELETE", re.compile(r"^/v1/tokens/(?P<token_name>[^/]+)$"), delete_token_handler, "master"),
]


def handler(event, context):
    """Lambda entry point. Routes requests based on HTTP method and path."""
    method = event.get("httpMethod", "")
    path = event.get("path", "")

    logger.info("Request: %s %s", method, path)

    try:
        for route_method, pattern, route_handler, required_permission in ROUTES:
            match = pattern.match(path)
            if match and method == route_method:
                # Check permission before invoking the handler
                perm_error = _check_permission(event, required_permission)
                if perm_error:
                    logger.info("Response: %s %s -> %s", method, path, perm_error["statusCode"])
                    return perm_error
                response = route_handler(event, match.groupdict())
                logger.info("Response: %s %s -> %s", method, path, response["statusCode"])
                return response

        # No route matched
        response = _error_response(405, "method_not_allowed", f"Method {method} not allowed for {path}")
        logger.info("Response: %s %s -> %s", method, path, response["statusCode"])
        return response

    except ValidationError as e:
        response = _error_response(400, e.error_code, e.message)
        logger.info("Response: %s %s -> %s", method, path, response["statusCode"])
        return response
    except Exception as e:
        logger.exception("Unhandled error: %s", str(e))
        response = _error_response(500, "internal_error", str(e))
        logger.info("Response: %s %s -> %s", method, path, response["statusCode"])
        return response
