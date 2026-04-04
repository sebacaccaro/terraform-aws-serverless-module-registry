"""Generate an OpenAPI 3.0 specification for the SE Registry API.

Builds the spec programmatically from the same source of truth as the API
itself (handler ROUTES table and validator patterns), then writes it as JSON.
"""

import argparse
import hashlib
import json
import os
import sys


# Patterns sourced from validators.py
PATH_PARAM_PATTERN = "^[a-z0-9_-]{1,64}$"
SEMVER_PATTERN = r"^\d+\.\d+\.\d+$"


def _error_ref():
    """Shorthand $ref for ErrorResponse."""
    return {"$ref": "#/components/schemas/ErrorResponse"}


def _error_response(description):
    return {
        "description": description,
        "content": {"application/json": {"schema": _error_ref()}},
    }


def _module_path_params():
    """Common path parameters for module endpoints."""
    return [
        {
            "name": "namespace",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "pattern": PATH_PARAM_PATTERN},
            "description": "Module namespace (1-64 lowercase alphanumeric, hyphens, underscores)",
        },
        {
            "name": "name",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "pattern": PATH_PARAM_PATTERN},
            "description": "Module name",
        },
        {
            "name": "system",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "pattern": PATH_PARAM_PATTERN},
            "description": "Target system (e.g. aws, gcp)",
        },
    ]


def _module_version_path_params():
    """Common path parameters for module endpoints that include a version."""
    return _module_path_params() + [
        {
            "name": "version",
            "in": "path",
            "required": True,
            "schema": {"type": "string", "pattern": SEMVER_PATTERN},
            "description": "Semantic version (X.Y.Z)",
        },
    ]


def _security():
    return [{"BearerAuth": []}]


def _build_schemas():
    """Build the components/schemas section."""
    return {
        "ModuleVersionList": {
            "type": "object",
            "properties": {
                "modules": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "versions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "version": {"type": "string"},
                                    },
                                    "required": ["version"],
                                },
                            },
                        },
                        "required": ["versions"],
                    },
                },
            },
            "required": ["modules"],
        },
        "UploadConfirmation": {
            "type": "object",
            "properties": {
                "namespace": {"type": "string"},
                "name": {"type": "string"},
                "system": {"type": "string"},
                "version": {"type": "string"},
            },
            "required": ["namespace", "name", "system", "version"],
        },
        "TokenRequest": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Token name"},
                "permission": {
                    "type": "string",
                    "enum": ["uploader", "downloader"],
                    "description": "Permission level for the token",
                },
            },
            "required": ["name", "permission"],
        },
        "TokenObject": {
            "type": "object",
            "properties": {
                "token_value": {"type": "string"},
                "token_name": {"type": "string"},
                "permission": {"type": "string", "enum": ["uploader", "downloader"]},
                "created_at": {"type": "string", "format": "date-time"},
            },
            "required": ["token_value", "token_name", "permission", "created_at"],
        },
        "TokenList": {
            "type": "object",
            "properties": {
                "tokens": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "token_name": {"type": "string"},
                            "permission": {"type": "string"},
                            "created_at": {"type": "string", "format": "date-time"},
                        },
                        "required": ["token_name", "permission", "created_at"],
                    },
                },
            },
            "required": ["tokens"],
        },
        "DeleteConfirmation": {
            "type": "object",
            "properties": {
                "message": {"type": "string"},
            },
            "required": ["message"],
        },
        "ErrorResponse": {
            "type": "object",
            "properties": {
                "error": {"type": "string"},
                "message": {"type": "string"},
            },
            "required": ["error", "message"],
        },
    }


def _build_paths():
    """Build the paths section with all 8 API routes."""
    return {
        "/v1/modules/{namespace}/{name}/{system}/versions": {
            "get": {
                "summary": "List module versions",
                "operationId": "listVersions",
                "tags": ["Modules"],
                "security": _security(),
                "parameters": _module_path_params(),
                "responses": {
                    "200": {
                        "description": "List of available versions",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ModuleVersionList"},
                            },
                        },
                    },
                    "400": _error_response("Invalid path parameters"),
                    "403": _error_response("Insufficient permissions"),
                    "404": _error_response("Module not found"),
                    "405": _error_response("Method not allowed"),
                    "500": _error_response("Internal server error"),
                    "502": _error_response("Upstream proxy error"),
                },
            },
        },
        "/v1/modules/{namespace}/{name}/{system}/{version}/download": {
            "get": {
                "summary": "Download a module version",
                "operationId": "downloadVersion",
                "tags": ["Modules"],
                "security": _security(),
                "parameters": _module_version_path_params(),
                "responses": {
                    "204": {
                        "description": "Redirect to download URL",
                        "headers": {
                            "X-Terraform-Get": {
                                "description": "Presigned S3 URL for the module archive",
                                "schema": {"type": "string", "format": "uri"},
                            },
                        },
                    },
                    "400": _error_response("Invalid path parameters or version"),
                    "403": _error_response("Insufficient permissions"),
                    "404": _error_response("Version not found"),
                    "405": _error_response("Method not allowed"),
                    "500": _error_response("Internal server error"),
                    "502": _error_response("Upstream proxy error"),
                },
            },
        },
        "/v1/modules/{namespace}/{name}/{system}/{version}": {
            "put": {
                "summary": "Upload a module version",
                "operationId": "uploadVersion",
                "tags": ["Modules"],
                "security": _security(),
                "parameters": _module_version_path_params(),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/octet-stream": {
                            "schema": {"type": "string", "format": "binary"},
                        },
                        "application/zip": {
                            "schema": {"type": "string", "format": "binary"},
                        },
                    },
                },
                "responses": {
                    "201": {
                        "description": "Module version uploaded successfully",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UploadConfirmation"},
                            },
                        },
                    },
                    "400": _error_response("Invalid path parameters or version"),
                    "403": _error_response("Insufficient permissions"),
                    "405": _error_response("Method not allowed"),
                    "409": _error_response("Version already exists"),
                    "500": _error_response("Internal server error"),
                },
            },
        },
        "/v1/pins/{namespace}/{name}/{system}/{version}": {
            "post": {
                "summary": "Pin a module version from the public registry",
                "operationId": "cacheVersion",
                "tags": ["Pins"],
                "security": _security(),
                "parameters": _module_version_path_params(),
                "responses": {
                    "201": {
                        "description": "Module version pinned successfully",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/UploadConfirmation"},
                            },
                        },
                    },
                    "400": _error_response("Invalid path parameters or version"),
                    "403": _error_response("Insufficient permissions"),
                    "404": _error_response("Module not found on public registry"),
                    "405": _error_response("Method not allowed"),
                    "409": _error_response("Version already exists locally"),
                    "500": _error_response("Internal server error"),
                    "502": _error_response("Failed to fetch from public registry"),
                },
            },
        },
        "/v1/tokens": {
            "post": {
                "summary": "Create a new API token",
                "operationId": "createToken",
                "tags": ["Tokens"],
                "security": _security(),
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/TokenRequest"},
                        },
                    },
                },
                "responses": {
                    "201": {
                        "description": "Token created successfully",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TokenObject"},
                            },
                        },
                    },
                    "400": _error_response("Invalid token name or permission"),
                    "403": _error_response("Insufficient permissions"),
                    "405": _error_response("Method not allowed"),
                    "409": _error_response("Token name already exists"),
                    "500": _error_response("Internal server error"),
                },
            },
            "get": {
                "summary": "List all API tokens",
                "operationId": "listTokens",
                "tags": ["Tokens"],
                "security": _security(),
                "responses": {
                    "200": {
                        "description": "List of tokens (without token values)",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TokenList"},
                            },
                        },
                    },
                    "403": _error_response("Insufficient permissions"),
                    "405": _error_response("Method not allowed"),
                    "500": _error_response("Internal server error"),
                },
            },
        },
        "/v1/tokens/{token_name}": {
            "delete": {
                "summary": "Delete an API token",
                "operationId": "deleteToken",
                "tags": ["Tokens"],
                "security": _security(),
                "parameters": [
                    {
                        "name": "token_name",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Name of the token to delete",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Token deleted successfully",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/DeleteConfirmation"},
                            },
                        },
                    },
                    "403": _error_response("Insufficient permissions"),
                    "404": _error_response("Token not found"),
                    "405": _error_response("Method not allowed"),
                    "500": _error_response("Internal server error"),
                },
            },
        },
        "/.well-known/{proxy+}": {
            "get": {
                "summary": "Terraform service discovery",
                "operationId": "serviceDiscovery",
                "tags": ["Discovery"],
                "security": _security(),
                "parameters": [
                    {
                        "name": "proxy+",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": "Discovery document path (e.g. terraform.json)",
                    },
                ],
                "responses": {
                    "200": {
                        "description": "Service discovery document",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "additionalProperties": True,
                                },
                            },
                        },
                    },
                    "403": _error_response("Insufficient permissions"),
                    "404": _error_response("Document not found"),
                    "500": _error_response("Internal server error"),
                },
            },
        },
    }


def build_openapi_spec():
    """Build the complete OpenAPI 3.0 specification as a Python dict.

    Returns:
        dict: A valid OpenAPI 3.0.3 document describing the SE Registry API.
    """
    spec = {
        "openapi": "3.0.3",
        "info": {
            "title": "SE Registry API",
            "description": "Terraform Module Registry API",
            "version": "",  # placeholder, filled with content hash below
        },
        "paths": _build_paths(),
        "components": {
            "securitySchemes": {
                "BearerAuth": {
                    "type": "http",
                    "scheme": "bearer",
                },
            },
            "schemas": _build_schemas(),
        },
    }

    # Compute a content hash for the version field so it changes when the spec changes.
    # Hash everything except the version field itself.
    spec_for_hash = json.dumps(spec, sort_keys=True, separators=(",", ":"))
    content_hash = hashlib.sha256(spec_for_hash.encode()).hexdigest()[:12]
    spec["info"]["version"] = content_hash

    return spec


def main():
    """Serialize the OpenAPI spec to JSON and write it to disk."""
    parser = argparse.ArgumentParser(
        description="Generate the SE Registry OpenAPI specification."
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output path. Can be a directory (openapi.json is created inside it) "
        "or a file path. Defaults to openapi.json in the project root.",
    )
    parser.add_argument(
        "-e",
        "--endpoint",
        default=None,
        help="API server URL to include in the spec (e.g. https://api.example.com). "
        "Sets the OpenAPI 'servers' field so tools like Swagger UI send requests there.",
    )
    args = parser.parse_args()

    spec = build_openapi_spec()

    endpoint = args.endpoint.rstrip("/") if args.endpoint else "https://your-api-domain.com"
    spec["servers"] = [
        {
            "url": "{baseUrl}",
            "variables": {
                "baseUrl": {
                    "default": endpoint,
                    "description": "API server URL",
                },
            },
        },
    ]

    spec_json = json.dumps(spec, indent=2, sort_keys=False) + "\n"

    if args.output is None:
        out_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "openapi.json")
    elif os.path.isdir(args.output) or args.output.endswith(os.sep):
        out_path = os.path.join(args.output, "openapi.json")
    else:
        out_path = args.output

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(spec_json)

    print(f"Wrote OpenAPI spec to {out_path}")


if __name__ == "__main__":
    main()
