"""Property-based tests for the private module registry.

Uses Hypothesis to verify correctness properties defined in the design document.
"""

import sys
import os
import re
import json
import string
from unittest.mock import patch, MagicMock

import boto3
import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validators import ValidationError, validate_path_param, validate_semver
from proxy import should_proxy

# Valid character set for path parameters
VALID_PATH_CHARS = string.ascii_lowercase + string.digits + "_-"


# --- Strategies ---

def valid_semver():
    """Strategy that generates strings matching ^\\d+\\.\\d+\\.\\d+$."""
    return st.builds(
        lambda major, minor, patch: f"{major}.{minor}.{patch}",
        st.integers(min_value=0, max_value=9999),
        st.integers(min_value=0, max_value=9999),
        st.integers(min_value=0, max_value=9999),
    )


def invalid_semver():
    """Strategy that generates strings NOT matching ^\\d+\\.\\d+\\.\\d+$."""
    return st.one_of(
        # Empty string
        st.just(""),
        # Missing components (only major, or major.minor)
        st.integers(min_value=0, max_value=999).map(str),
        st.builds(
            lambda a, b: f"{a}.{b}",
            st.integers(min_value=0, max_value=999),
            st.integers(min_value=0, max_value=999),
        ),
        # Extra components (four-part version)
        st.builds(
            lambda a, b, c, d: f"{a}.{b}.{c}.{d}",
            st.integers(min_value=0, max_value=99),
            st.integers(min_value=0, max_value=99),
            st.integers(min_value=0, max_value=99),
            st.integers(min_value=0, max_value=99),
        ),
        # Pre-release suffix
        valid_semver().map(lambda v: v + "-beta"),
        # Leading 'v' prefix
        valid_semver().map(lambda v: "v" + v),
        # Arbitrary text that doesn't match semver
        st.text(min_size=1, max_size=32).filter(
            lambda s: not re.match(r"^\d+\.\d+\.\d+$", s)
        ),
    )


def valid_path_params():
    """Strategy that generates strings matching ^[a-z0-9_-]{1,64}$."""
    return st.text(alphabet=VALID_PATH_CHARS, min_size=1, max_size=64)


def invalid_path_params():
    """Strategy that generates strings NOT matching ^[a-z0-9_-]{1,64}$."""
    return st.one_of(
        # Empty string
        st.just(""),
        # Too long (65+ valid chars)
        st.text(alphabet=VALID_PATH_CHARS, min_size=65, max_size=128),
        # Contains at least one invalid character (uppercase, special, space, etc.)
        st.text(min_size=1, max_size=64).filter(
            lambda s: not re.match(r"^[a-z0-9_-]{1,64}$", s)
        ),
    )


# --- Property 10: Path parameter validation ---
# Feature: private-module-registry, Property 10: Path parameter validation
# Validates: Requirements 10.1, 10.2, 10.3


PARAM_NAMES = ("namespace", "name", "system")


@given(value=valid_path_params(), param_name=st.sampled_from(PARAM_NAMES))
@settings(max_examples=100)
def test_property10_valid_path_params_accepted(value, param_name):
    """For any string matching ^[a-z0-9_-]{1,64}$, validate_path_param SHALL accept it."""
    validate_path_param(param_name, value)  # Should not raise


@given(value=invalid_path_params(), param_name=st.sampled_from(PARAM_NAMES))
@settings(max_examples=100)
def test_property10_invalid_path_params_rejected(value, param_name):
    """For any string NOT matching ^[a-z0-9_-]{1,64}$, validate_path_param SHALL reject it
    with error_code 'invalid_parameter' and a message identifying the parameter."""
    with pytest.raises(ValidationError) as exc_info:
        validate_path_param(param_name, value)
    assert exc_info.value.error_code == "invalid_parameter"
    assert param_name in exc_info.value.message


# --- Property 4: Semver validation ---
# Feature: private-module-registry, Property 4: Semver validation
# Validates: Requirements 4.2, 4.3


@given(version=valid_semver())
@settings(max_examples=100)
def test_property4_valid_semver_accepted(version):
    """For any string matching ^\\d+\\.\\d+\\.\\d+$, validate_semver SHALL accept it."""
    validate_semver(version)  # Should not raise


@given(version=invalid_semver())
@settings(max_examples=100)
def test_property4_invalid_semver_rejected(version):
    """For any string NOT matching ^\\d+\\.\\d+\\.\\d+$, validate_semver SHALL reject it
    with error_code 'invalid_version' and return HTTP 400."""
    with pytest.raises(ValidationError) as exc_info:
        validate_semver(version)
    assert exc_info.value.error_code == "invalid_version"
    assert "not valid semantic versioning" in exc_info.value.message


# --- Strategies for module operations ---

def valid_module_id():
    """Strategy that generates a valid (namespace, name, system) tuple."""
    return st.tuples(
        valid_path_params(),
        valid_path_params(),
        valid_path_params(),
    )


# --- Property 1: List versions returns all unique versions in protocol format ---
# Feature: private-module-registry, Property 1: List versions returns all unique versions in protocol format
# Validates: Requirements 2.1, 2.2, 2.5


@given(
    module_id=valid_module_id(),
    version_set=st.frozensets(valid_semver(), min_size=0, max_size=10),
    extra_files_per_version=st.integers(min_value=1, max_value=3),
)
@settings(max_examples=100)
def test_property1_list_versions_returns_unique_versions_in_protocol_format(
    module_id, version_set, extra_files_per_version
):
    """For any module identifier and any set of S3 objects (including duplicates),
    list_versions SHALL return exactly the unique version strings in protocol format."""
    namespace, name, system = module_id
    prefix = f"{namespace}/{name}/{system}/"

    # Build mock S3 objects — multiple files per version to test deduplication
    s3_objects = []
    for version in version_set:
        for i in range(extra_files_per_version):
            key = f"{prefix}{version}/{name}-{system}-{version}.zip"
            if i > 0:
                key = f"{prefix}{version}/extra-file-{i}.txt"
            s3_objects.append({"Key": key})

    # Mock the S3 paginator to return our objects
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [{"Contents": s3_objects}] if s3_objects else [{}]

    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket"}):
        import s3_client
        old_client = s3_client._s3_client
        s3_client._s3_client = mock_client
        try:
            import handler
            event = {
                "httpMethod": "GET",
                "path": f"/v1/modules/{namespace}/{name}/{system}/versions",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            }
            response = handler.handler(event, None)

            if not version_set:
                assert response["statusCode"] == 404
            else:
                assert response["statusCode"] == 200
                body = json.loads(response["body"])
                returned_versions = {v["version"] for v in body["modules"][0]["versions"]}
                assert returned_versions == set(version_set)
                # Verify protocol format structure
                assert "modules" in body
                assert len(body["modules"]) == 1
                assert "versions" in body["modules"][0]
        finally:
            s3_client._s3_client = old_client


# --- Property 2: Download returns presigned URL for correct S3 key ---
# Feature: private-module-registry, Property 2: Download returns presigned URL for correct S3 key
# Validates: Requirements 3.1, 3.4


@given(module_id=valid_module_id(), version=valid_semver())
@settings(max_examples=100)
def test_property2_download_returns_presigned_url_for_correct_key(module_id, version):
    """For any valid module identifier where the archive exists in S3,
    download SHALL return HTTP 204 with X-Terraform-Get referencing the correct S3 key."""
    namespace, name, system = module_id
    expected_key = f"{namespace}/{name}/{system}/{version}/{name}-{system}-{version}.zip"
    fake_url = f"https://test-bucket.s3.amazonaws.com/{expected_key}?X-Amz-Signature=fake"

    mock_client = MagicMock()
    # head_object succeeds (object exists)
    mock_client.head_object.return_value = {}
    mock_client.generate_presigned_url.return_value = fake_url
    # Make exceptions available for head_object error handling
    mock_client.exceptions = MagicMock()

    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket"}):
        import s3_client
        old_client = s3_client._s3_client
        s3_client._s3_client = mock_client
        try:
            import handler
            event = {
                "httpMethod": "GET",
                "path": f"/v1/modules/{namespace}/{name}/{system}/{version}/download",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            }
            response = handler.handler(event, None)

            assert response["statusCode"] == 204
            assert "X-Terraform-Get" in response["headers"]
            # Verify presigned URL was generated for the correct key
            mock_client.generate_presigned_url.assert_called_once_with(
                "get_object",
                Params={"Bucket": "test-bucket", "Key": expected_key},
                ExpiresIn=300,
            )
            assert response["headers"]["X-Terraform-Get"] == fake_url
        finally:
            s3_client._s3_client = old_client


# --- Property 3: Upload round trip ---
# Feature: private-module-registry, Property 3: Upload round trip
# Validates: Requirements 4.1, 4.5, 7.1


@given(
    module_id=valid_module_id(),
    version=valid_semver(),
    payload=st.binary(min_size=1, max_size=1024),
)
@settings(max_examples=100)
def test_property3_upload_round_trip(module_id, version, payload):
    """For any valid module identifier, semver version, and binary payload,
    uploading SHALL store at the correct S3 key and return HTTP 201 with module metadata."""
    from botocore.exceptions import ClientError as BotoClientError

    namespace, name, system = module_id
    expected_key = f"{namespace}/{name}/{system}/{version}/{name}-{system}-{version}.zip"

    mock_client = MagicMock()
    # head_object raises 404 (object doesn't exist yet)
    mock_client.head_object.side_effect = BotoClientError(
        {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
    )
    mock_client.exceptions.ClientError = BotoClientError
    mock_client.put_object.return_value = {}

    import base64
    encoded_body = base64.b64encode(payload).decode("ascii")

    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket"}):
        import s3_client
        old_client = s3_client._s3_client
        s3_client._s3_client = mock_client
        try:
            import handler
            event = {
                "httpMethod": "PUT",
                "path": f"/v1/modules/{namespace}/{name}/{system}/{version}",
                "body": encoded_body,
                "isBase64Encoded": True,
                "requestContext": {"authorizer": {"permission": "uploader", "is_master": "false"}},
            }
            response = handler.handler(event, None)

            assert response["statusCode"] == 201
            body = json.loads(response["body"])
            assert body["namespace"] == namespace
            assert body["name"] == name
            assert body["system"] == system
            assert body["version"] == version

            # Verify put_object was called with correct key and payload
            mock_client.put_object.assert_called_once_with(
                Bucket="test-bucket",
                Key=expected_key,
                Body=payload,
            )
        finally:
            s3_client._s3_client = old_client


# --- Strategies for error-triggering requests ---

def error_triggering_events():
    """Strategy that generates API Gateway events which trigger error responses.

    Covers: invalid path params (400), invalid semver (400), unsupported method (405),
    unmatched paths (405), and permission denied (403).
    """
    return st.one_of(
        # Invalid path param → 400
        st.builds(
            lambda ns: {
                "httpMethod": "GET",
                "path": f"/v1/modules/{ns}/validname/validsys/versions",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            invalid_path_params(),
        ),
        # Invalid semver in download → 400
        st.builds(
            lambda ver: {
                "httpMethod": "GET",
                "path": f"/v1/modules/validns/validname/validsys/{ver}/download",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            invalid_semver(),
        ),
        # Unsupported method on valid path → 405
        st.builds(
            lambda method, ns, name, sys: {
                "httpMethod": method,
                "path": f"/v1/modules/{ns}/{name}/{sys}/versions",
                "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}},
            },
            st.sampled_from(["POST", "DELETE", "PATCH"]),
            valid_path_params(),
            valid_path_params(),
            valid_path_params(),
        ),
        # Completely unmatched path → 405
        st.builds(
            lambda seg: {
                "httpMethod": "GET",
                "path": f"/v1/unknown/{seg}",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=16),
        ),
        # Downloader attempting upload → 403
        st.builds(
            lambda ns, name, sys, ver: {
                "httpMethod": "PUT",
                "path": f"/v1/modules/{ns}/{name}/{sys}/{ver}",
                "body": "data",
                "isBase64Encoded": False,
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            valid_path_params(),
            valid_path_params(),
            valid_path_params(),
            valid_semver(),
        ),
    )


# --- Property 8: Error response format consistency ---
# Feature: private-module-registry, Property 8: Error response format consistency
# Validates: Requirements 9.3


@given(event=error_triggering_events())
@settings(max_examples=100)
def test_property8_error_response_format_consistency(event):
    """For any request that results in an error status code (4xx or 5xx),
    the response body SHALL be valid JSON containing both 'error' and 'message' fields."""
    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket"}):
        import handler
        response = handler.handler(event, None)

        status = response["statusCode"]
        if status >= 400:
            body = json.loads(response["body"])
            assert "error" in body, f"Error response missing 'error' field: {body}"
            assert "message" in body, f"Error response missing 'message' field: {body}"
            assert isinstance(body["error"], str)
            assert isinstance(body["message"], str)


# --- Property 9: Unsupported method returns 405 ---
# Feature: private-module-registry, Property 9: Unsupported method returns 405
# Validates: Requirements 9.4


def unmatched_method_path_events():
    """Strategy generating method+path combos that don't match any defined route."""
    return st.one_of(
        # Wrong method on a valid module versions path (not PUT — PUT matches upload route with "versions" as version param)
        st.builds(
            lambda method, ns, name, sys: {
                "httpMethod": method,
                "path": f"/v1/modules/{ns}/{name}/{sys}/versions",
                "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}},
            },
            st.sampled_from(["POST", "DELETE", "PATCH"]),
            valid_path_params(),
            valid_path_params(),
            valid_path_params(),
        ),
        # Wrong method on download path
        st.builds(
            lambda method, ns, name, sys, ver: {
                "httpMethod": method,
                "path": f"/v1/modules/{ns}/{name}/{sys}/{ver}/download",
                "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}},
            },
            st.sampled_from(["POST", "DELETE", "PATCH", "PUT"]),
            valid_path_params(),
            valid_path_params(),
            valid_path_params(),
            valid_semver(),
        ),
        # Wrong method on upload path
        st.builds(
            lambda method, ns, name, sys, ver: {
                "httpMethod": method,
                "path": f"/v1/modules/{ns}/{name}/{sys}/{ver}",
                "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}},
            },
            st.sampled_from(["POST", "DELETE", "PATCH"]),
            valid_path_params(),
            valid_path_params(),
            valid_path_params(),
            valid_semver(),
        ),
        # Completely unknown paths
        st.builds(
            lambda method, seg: {
                "httpMethod": method,
                "path": f"/unknown/{seg}",
                "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}},
            },
            st.sampled_from(["GET", "POST", "PUT", "DELETE", "PATCH"]),
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=16),
        ),
    )


@given(event=unmatched_method_path_events())
@settings(max_examples=100)
def test_property9_unsupported_method_returns_405(event):
    """For any HTTP method and path combination that does not match a defined route,
    the handler SHALL return HTTP 405."""
    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket"}):
        import handler
        response = handler.handler(event, None)

        assert response["statusCode"] == 405, (
            f"Expected 405 for {event['httpMethod']} {event['path']}, got {response['statusCode']}"
        )
        body = json.loads(response["body"])
        assert body["error"] == "method_not_allowed"


# --- Property 11: Request logging ---
# Feature: private-module-registry, Property 11: Request logging
# Validates: Requirements 9.2


def any_request_event():
    """Strategy generating arbitrary valid API Gateway events."""
    return st.one_of(
        # Valid module list versions
        st.builds(
            lambda ns, name, sys: {
                "httpMethod": "GET",
                "path": f"/v1/modules/{ns}/{name}/{sys}/versions",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            valid_path_params(),
            valid_path_params(),
            valid_path_params(),
        ),
        # Unknown path
        st.builds(
            lambda method, seg: {
                "httpMethod": method,
                "path": f"/unknown/{seg}",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            st.sampled_from(["GET", "POST", "PUT", "DELETE"]),
            st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=16),
        ),
        # Invalid path param (triggers 400)
        st.builds(
            lambda bad: {
                "httpMethod": "GET",
                "path": f"/v1/modules/{bad}/name/sys/versions",
                "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
            },
            invalid_path_params(),
        ),
    )


@given(event=any_request_event())
@settings(max_examples=100)
def test_property11_request_logging(event):
    """For any incoming request, the handler SHALL log the HTTP method,
    request path, and response status code."""
    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket"}):
        import handler

        # Mock S3 for list_versions calls so they don't fail on boto3
        mock_client = MagicMock()
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = mock_paginator

        import s3_client
        old_client = s3_client._s3_client
        s3_client._s3_client = mock_client

        try:
            with patch.object(handler.logger, "info") as mock_log:
                response = handler.handler(event, None)

                method = event["httpMethod"]
                path = event["path"]
                status = response["statusCode"]

                log_messages = [
                    call.args for call in mock_log.call_args_list
                ]

                # Verify request was logged (method + path)
                # Check that at least one log call contains both method and path as arguments
                request_logged = any(
                    len(args) >= 3 and args[1] == method and args[2] == path
                    for args in log_messages
                )
                assert request_logged, (
                    f"Request {method} {path} not logged. Log calls: {log_messages}"
                )

                # Verify response status was logged
                status_logged = any(
                    status in args
                    for args in log_messages
                    for _ in [None]  # just to allow the nested comprehension
                    if len(args) >= 4
                )
                assert status_logged, (
                    f"Response status {status} not logged. Log calls: {log_messages}"
                )
        finally:
            s3_client._s3_client = old_client


# --- Property 6: Proxy decision with allow/deny lists ---
# Feature: private-module-registry, Property 6: Proxy decision with allow/deny lists
# Validates: Requirements 6.7, 6.8, 6.9


def prefix_expressions(namespace_st, name_st):
    """Strategy that generates realistic prefix expressions for allow/deny lists.

    Generates prefixes like "hashicorp/", "myorg/vpc", or just a namespace prefix.
    Also includes prefixes derived from the actual namespace/name to ensure
    interesting overlap with the module under test.
    """
    return st.one_of(
        # Namespace-only prefix (e.g. "hashicorp/")
        namespace_st.map(lambda ns: f"{ns}/"),
        # Full namespace/name prefix
        st.builds(lambda ns, n: f"{ns}/{n}", namespace_st, name_st),
        # Partial namespace prefix (first few chars)
        namespace_st.map(lambda ns: ns[:max(1, len(ns) // 2)]),
    )


@given(
    namespace=valid_path_params(),
    name=valid_path_params(),
    allow_list=st.lists(prefix_expressions(valid_path_params(), valid_path_params()), min_size=0, max_size=5),
    deny_list=st.lists(prefix_expressions(valid_path_params(), valid_path_params()), min_size=0, max_size=5),
)
@settings(max_examples=100)
def test_property6_proxy_decision_with_allow_deny_lists(namespace, name, allow_list, deny_list):
    """For any module identifier and any allow/deny lists, should_proxy SHALL return True
    iff (a) the module does NOT match any deny prefix AND (b) either the allow list is
    empty OR the module matches at least one allow prefix. Deny list always takes precedence.

    **Validates: Requirements 6.7, 6.8, 6.9**
    """
    module_path = f"{namespace}/{name}"
    config = {"allow_list": allow_list, "deny_list": deny_list}

    result = should_proxy(namespace, name, config)

    # Compute expected result independently
    denied = any(module_path.startswith(prefix) for prefix in deny_list)
    allowed = (not allow_list) or any(module_path.startswith(prefix) for prefix in allow_list)
    expected = (not denied) and allowed

    assert result == expected, (
        f"should_proxy({namespace!r}, {name!r}, ...) returned {result}, expected {expected}. "
        f"module_path={module_path!r}, allow_list={allow_list}, deny_list={deny_list}"
    )


# --- Property 7: Proxy disabled prevents external requests ---
# Feature: private-module-registry, Property 7: Proxy disabled prevents external requests
# Validates: Requirements 6.4


@given(
    module_id=valid_module_id(),
    version=valid_semver(),
    route=st.sampled_from(["list_versions", "download"]),
)
@settings(max_examples=100)
def test_property7_proxy_disabled_prevents_external_requests(module_id, version, route):
    """For any module identifier not found in the local S3 bucket, when the proxy feature
    is disabled, the handler SHALL return HTTP 404 without making any outbound HTTP request.

    **Validates: Requirements 6.4**
    """
    from botocore.exceptions import ClientError as BotoClientError

    namespace, name, system = module_id

    mock_client = MagicMock()

    if route == "list_versions":
        # S3 returns no objects
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [{}]
        mock_client.get_paginator.return_value = mock_paginator
        path = f"/v1/modules/{namespace}/{name}/{system}/versions"
    else:
        # head_object raises 404 (object doesn't exist)
        mock_client.head_object.side_effect = BotoClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        mock_client.exceptions.ClientError = BotoClientError
        path = f"/v1/modules/{namespace}/{name}/{system}/{version}/download"

    event = {
        "httpMethod": "GET",
        "path": path,
        "requestContext": {"authorizer": {"permission": "downloader", "is_master": "false"}},
    }

    with patch.dict(os.environ, {
        "MODULES_BUCKET": "test-bucket",
        "PROXY_ENABLED": "false",
        "PROXY_ALLOW_LIST": "",
        "PROXY_DENY_LIST": "",
    }):
        import s3_client
        old_client = s3_client._s3_client
        s3_client._s3_client = mock_client
        try:
            with patch("handler.proxy_request") as mock_proxy:
                import handler
                response = handler.handler(event, None)

                assert response["statusCode"] == 404, (
                    f"Expected 404 for {route} with proxy disabled, got {response['statusCode']}"
                )
                body = json.loads(response["body"])
                assert body["error"] == "not_found"

                # Verify no outbound proxy request was made
                mock_proxy.assert_not_called()
        finally:
            s3_client._s3_client = old_client


# --- Property 13: Token creation round trip ---
# Feature: private-module-registry, Property 13: Token creation round trip
# Validates: Requirements 12.1, 12.5


def _create_token_table(table_name):
    """Create a DynamoDB table matching the Token_Table schema for testing."""
    ddb = boto3.client("dynamodb", region_name="us-east-1")
    ddb.create_table(
        TableName=table_name,
        KeySchema=[{"AttributeName": "token_value", "KeyType": "HASH"}],
        AttributeDefinitions=[
            {"AttributeName": "token_value", "AttributeType": "S"},
            {"AttributeName": "token_name", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": "token_name-index",
                "KeySchema": [{"AttributeName": "token_name", "KeyType": "HASH"}],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        BillingMode="PAY_PER_REQUEST",
    )


def _token_name_strategy():
    """Strategy for valid token names: non-empty printable strings, max 64 chars."""
    return st.text(
        alphabet=st.characters(whitelist_categories=("L", "N", "P", "S"), whitelist_characters="-_ "),
        min_size=1,
        max_size=64,
    ).filter(lambda s: s.strip())


@given(
    token_name=_token_name_strategy(),
    permission=st.sampled_from(["uploader", "downloader"]),
)
@settings(max_examples=100)
def test_property13_token_creation_round_trip(token_name, permission):
    """For any valid token name and any valid permission, creating a token via POST /v1/tokens
    and then listing tokens via GET /v1/tokens SHALL include the created token with the correct
    name, permission, and a valid created_at timestamp.

    **Validates: Requirements 12.1, 12.5**
    """
    import datetime

    table_name = "test-token-table"

    master_context = {
        "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}}
    }

    with mock_aws():
        _create_token_table(table_name)

        with patch.dict(os.environ, {
            "TOKEN_TABLE_NAME": table_name,
            "MODULES_BUCKET": "test-bucket",
            "AWS_DEFAULT_REGION": "us-east-1",
        }):
            import handler
            # handler caches TOKEN_TABLE_NAME at import time, so patch it directly
            old_table_name = handler.TOKEN_TABLE_NAME
            handler.TOKEN_TABLE_NAME = table_name
            try:
                # Step 1: Create a token via POST /v1/tokens
                create_event = {
                    **master_context,
                    "httpMethod": "POST",
                    "path": "/v1/tokens",
                    "body": json.dumps({"name": token_name, "permission": permission}),
                }
                create_response = handler.handler(create_event, None)

                assert create_response["statusCode"] == 201, (
                    f"Expected 201 for token creation, got {create_response['statusCode']}: {create_response['body']}"
                )

                create_body = json.loads(create_response["body"])

                # Assert POST response includes required fields
                assert "token_value" in create_body, "POST response missing 'token_value'"
                assert "token_name" in create_body, "POST response missing 'token_name'"
                assert "permission" in create_body, "POST response missing 'permission'"
                assert "created_at" in create_body, "POST response missing 'created_at'"
                assert create_body["token_name"] == token_name
                assert create_body["permission"] == permission

                # Validate created_at is a valid ISO 8601 timestamp
                datetime.datetime.fromisoformat(create_body["created_at"])

                # Step 2: List tokens via GET /v1/tokens
                list_event = {
                    **master_context,
                    "httpMethod": "GET",
                    "path": "/v1/tokens",
                }
                list_response = handler.handler(list_event, None)

                assert list_response["statusCode"] == 200, (
                    f"Expected 200 for token listing, got {list_response['statusCode']}: {list_response['body']}"
                )

                list_body = json.loads(list_response["body"])
                tokens = list_body["tokens"]

                # Assert the created token appears in the list with correct name and permission
                matching = [t for t in tokens if t["token_name"] == token_name]
                assert len(matching) >= 1, (
                    f"Created token '{token_name}' not found in token list: {tokens}"
                )

                found = matching[0]
                assert found["permission"] == permission, (
                    f"Expected permission '{permission}', got '{found['permission']}'"
                )
                assert "created_at" in found, "Listed token missing 'created_at'"

                # Validate created_at in the listed token is a valid ISO 8601 timestamp
                datetime.datetime.fromisoformat(found["created_at"])

                # Assert GET response does NOT include token_value for any token
                for t in tokens:
                    assert "token_value" not in t, (
                        f"GET /v1/tokens should NOT expose token_value, but found it in: {t}"
                    )
            finally:
                handler.TOKEN_TABLE_NAME = old_table_name


# --- Property 14: Token management master-only access ---
# Feature: private-module-registry, Property 14: Token management master-only access
# Validates: Requirements 12.8, 12.9


@given(
    permission=st.sampled_from(["uploader", "downloader"]),
    operation=st.sampled_from(["post_create", "get_list", "delete_token"]),
    token_name=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=16),
)
@settings(max_examples=100)
def test_property14_token_management_master_only_access(permission, operation, token_name):
    """For any non-master Auth_Token (regardless of permission level), requests to
    POST /v1/tokens, GET /v1/tokens, or DELETE /v1/tokens/{token_name} SHALL return HTTP 403.

    **Validates: Requirements 12.8, 12.9**
    """
    non_master_context = {
        "requestContext": {"authorizer": {"permission": permission, "is_master": "false"}}
    }

    if operation == "post_create":
        event = {
            **non_master_context,
            "httpMethod": "POST",
            "path": "/v1/tokens",
            "body": json.dumps({"name": "test", "permission": "uploader"}),
        }
    elif operation == "get_list":
        event = {
            **non_master_context,
            "httpMethod": "GET",
            "path": "/v1/tokens",
        }
    else:  # delete_token
        event = {
            **non_master_context,
            "httpMethod": "DELETE",
            "path": f"/v1/tokens/{token_name}",
        }

    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket", "TOKEN_TABLE_NAME": "test-tokens"}):
        import handler
        response = handler.handler(event, None)

        assert response["statusCode"] == 403, (
            f"Expected 403 for non-master {permission} on {operation}, got {response['statusCode']}"
        )
        body = json.loads(response["body"])
        assert body["error"] == "forbidden"
        assert body["message"] == "Only the master token can manage tokens"


# --- Property 15: Token name uniqueness ---
# Feature: private-module-registry, Property 15: Token name uniqueness
# Validates: Requirements 12.4


@given(
    token_name=_token_name_strategy(),
    permission=st.sampled_from(["uploader", "downloader"]),
)
@settings(max_examples=100)
def test_property15_token_name_uniqueness(token_name, permission):
    """For any token name that already exists in the Token_Table, a POST /v1/tokens
    request with the same name SHALL return HTTP 409.

    **Validates: Requirements 12.4**
    """
    table_name = "test-token-table"

    master_context = {
        "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}}
    }

    with mock_aws():
        _create_token_table(table_name)

        with patch.dict(os.environ, {
            "TOKEN_TABLE_NAME": table_name,
            "MODULES_BUCKET": "test-bucket",
            "AWS_DEFAULT_REGION": "us-east-1",
        }):
            import handler
            old_table_name = handler.TOKEN_TABLE_NAME
            handler.TOKEN_TABLE_NAME = table_name
            try:
                # Step 1: Create a token (should succeed with 201)
                create_event = {
                    **master_context,
                    "httpMethod": "POST",
                    "path": "/v1/tokens",
                    "body": json.dumps({"name": token_name, "permission": permission}),
                }
                first_response = handler.handler(create_event, None)
                assert first_response["statusCode"] == 201, (
                    f"Expected 201 for first token creation, got {first_response['statusCode']}: {first_response['body']}"
                )

                # Step 2: Attempt to create another token with the SAME name (should return 409)
                duplicate_event = {
                    **master_context,
                    "httpMethod": "POST",
                    "path": "/v1/tokens",
                    "body": json.dumps({"name": token_name, "permission": permission}),
                }
                second_response = handler.handler(duplicate_event, None)

                assert second_response["statusCode"] == 409, (
                    f"Expected 409 for duplicate token name, got {second_response['statusCode']}: {second_response['body']}"
                )

                body = json.loads(second_response["body"])
                assert body["error"] == "conflict", (
                    f"Expected error 'conflict', got '{body['error']}'"
                )
                assert token_name in body["message"], (
                    f"Expected token name '{token_name}' in error message, got: {body['message']}"
                )
            finally:
                handler.TOKEN_TABLE_NAME = old_table_name


# --- Property 16: Token deletion ---
# Feature: private-module-registry, Property 16: Token deletion
# Validates: Requirements 12.6, 12.7


def _token_name_no_slash_strategy():
    """Strategy for valid token names without '/' (which breaks URL path routing)."""
    return _token_name_strategy().filter(lambda s: "/" not in s)


@given(
    token_name=_token_name_no_slash_strategy(),
    permission=st.sampled_from(["uploader", "downloader"]),
)
@settings(max_examples=100)
def test_property16_token_deletion(token_name, permission):
    """For any token name that exists in the Token_Table, a DELETE /v1/tokens/{token_name}
    request with the master token SHALL remove the token, and subsequent listing SHALL NOT
    include the deleted token. Also, deleting a non-existent token SHALL return 404.

    **Validates: Requirements 12.6, 12.7**
    """
    table_name = "test-token-table"

    master_context = {
        "requestContext": {"authorizer": {"permission": "master", "is_master": "true"}}
    }

    with mock_aws():
        _create_token_table(table_name)

        with patch.dict(os.environ, {
            "TOKEN_TABLE_NAME": table_name,
            "MODULES_BUCKET": "test-bucket",
            "AWS_DEFAULT_REGION": "us-east-1",
        }):
            import handler
            old_table_name = handler.TOKEN_TABLE_NAME
            handler.TOKEN_TABLE_NAME = table_name
            try:
                # Step 1: Create a token via POST /v1/tokens
                create_event = {
                    **master_context,
                    "httpMethod": "POST",
                    "path": "/v1/tokens",
                    "body": json.dumps({"name": token_name, "permission": permission}),
                }
                create_response = handler.handler(create_event, None)
                assert create_response["statusCode"] == 201, (
                    f"Expected 201 for token creation, got {create_response['statusCode']}: {create_response['body']}"
                )

                # Step 2: Delete the token via DELETE /v1/tokens/{token_name}
                delete_event = {
                    **master_context,
                    "httpMethod": "DELETE",
                    "path": f"/v1/tokens/{token_name}",
                }
                delete_response = handler.handler(delete_event, None)
                assert delete_response["statusCode"] == 200, (
                    f"Expected 200 for token deletion, got {delete_response['statusCode']}: {delete_response['body']}"
                )
                delete_body = json.loads(delete_response["body"])
                assert delete_body["message"] == f"Token '{token_name}' deleted", (
                    f"Expected deletion message for '{token_name}', got: {delete_body['message']}"
                )

                # Step 3: List tokens via GET /v1/tokens — deleted token must NOT appear
                list_event = {
                    **master_context,
                    "httpMethod": "GET",
                    "path": "/v1/tokens",
                }
                list_response = handler.handler(list_event, None)
                assert list_response["statusCode"] == 200
                list_body = json.loads(list_response["body"])
                token_names = [t["token_name"] for t in list_body["tokens"]]
                assert token_name not in token_names, (
                    f"Deleted token '{token_name}' should not appear in token list, but found: {token_names}"
                )

                # Step 4: Delete the same token again — should return 404
                delete_again_response = handler.handler(delete_event, None)
                assert delete_again_response["statusCode"] == 404, (
                    f"Expected 404 for deleting non-existent token, got {delete_again_response['statusCode']}: {delete_again_response['body']}"
                )
                not_found_body = json.loads(delete_again_response["body"])
                assert not_found_body["error"] == "not_found", (
                    f"Expected error 'not_found', got '{not_found_body['error']}'"
                )
            finally:
                handler.TOKEN_TABLE_NAME = old_table_name


# --- Property 5: Authorizer token validation with DynamoDB and Secrets Manager ---
# Feature: private-module-registry, Property 5: Authorizer token validation with DynamoDB and Secrets Manager
# Validates: Requirements 5.3, 5.5, 5.6


def _token_value_strategy():
    """Strategy for token values: hex strings like secrets.token_hex()."""
    return st.text(alphabet="0123456789abcdef", min_size=8, max_size=64)


@given(
    master_token=_token_value_strategy(),
    request_token=_token_value_strategy(),
    ddb_tokens=st.lists(
        st.tuples(
            _token_value_strategy(),
            _token_name_strategy(),
            st.sampled_from(["uploader", "downloader"]),
        ),
        min_size=0,
        max_size=5,
    ),
)
@settings(max_examples=100)
def test_property5_authorizer_token_validation(master_token, request_token, ddb_tokens):
    """For any token string, for any master token value, and for any set of tokens in the
    Token_Table, the authorizer SHALL return an Allow policy with permission: "master" if
    the token matches the master token, an Allow policy with the stored permission if the
    token exists in the Token_Table, and a Deny policy otherwise.

    **Validates: Requirements 5.3, 5.5, 5.6**
    """
    table_name = "test-token-table"
    method_arn = "arn:aws:execute-api:us-east-1:123456789:abc123/prod/GET/v1/modules"

    # Ensure ddb_tokens have unique token_values and none match master_token
    seen_values = {master_token}
    unique_ddb_tokens = []
    for tv, tn, perm in ddb_tokens:
        if tv not in seen_values:
            seen_values.add(tv)
            unique_ddb_tokens.append((tv, tn, perm))

    with mock_aws():
        # Create Secrets Manager secret
        sm = boto3.client("secretsmanager", region_name="us-east-1")
        sm.create_secret(Name="test-master-token", SecretString=master_token)
        secret_arn = sm.describe_secret(SecretId="test-master-token")["ARN"]

        # Create DynamoDB table and populate tokens
        _create_token_table(table_name)
        ddb = boto3.resource("dynamodb", region_name="us-east-1")
        table = ddb.Table(table_name)
        for tv, tn, perm in unique_ddb_tokens:
            table.put_item(Item={
                "token_value": tv,
                "token_name": tn,
                "permission": perm,
                "created_at": "2024-01-01T00:00:00Z",
            })

        with patch.dict(os.environ, {
            "TOKEN_TABLE_NAME": table_name,
            "MASTER_TOKEN_SECRET_ARN": secret_arn,
            "AWS_DEFAULT_REGION": "us-east-1",
        }):
            import authorizer
            # Clear the cached master token so each test iteration fetches fresh
            authorizer._master_token_cache = None

            event = {
                "authorizationToken": f"Bearer {request_token}",
                "methodArn": method_arn,
            }
            result = authorizer.handler(event, None)

            policy_effect = result["policyDocument"]["Statement"][0]["Effect"]

            if request_token == master_token:
                # Should be Allow with master permission
                assert policy_effect == "Allow", (
                    f"Expected Allow for master token, got {policy_effect}"
                )
                assert result["context"]["permission"] == "master"
                assert result["context"]["is_master"] == "true"
            else:
                # Check if token exists in DynamoDB
                ddb_match = None
                for tv, tn, perm in unique_ddb_tokens:
                    if tv == request_token:
                        ddb_match = perm
                        break

                if ddb_match is not None:
                    assert policy_effect == "Allow", (
                        f"Expected Allow for DynamoDB token, got {policy_effect}"
                    )
                    assert result["context"]["permission"] == ddb_match
                    assert result["context"]["is_master"] == "false"
                else:
                    assert policy_effect == "Deny", (
                        f"Expected Deny for unknown token, got {policy_effect}"
                    )


# --- Property 12: Permission-based access control ---
# Feature: private-module-registry, Property 12: Permission-based access control
# Validates: Requirements 5.7, 5.8, 5.9


@given(
    permission=st.sampled_from(["downloader", "uploader"]),
    module_id=valid_module_id(),
    version=valid_semver(),
    method=st.sampled_from(["GET_versions", "GET_download", "PUT_upload"]),
)
@settings(max_examples=100)
def test_property12_permission_based_access_control(permission, module_id, version, method):
    """For any authenticated request with a 'downloader' permission token, the handler SHALL
    allow GET requests to module endpoints and return HTTP 403 for PUT requests. For any
    authenticated request with an 'uploader' permission token, the handler SHALL allow both
    GET and PUT requests to module endpoints.

    **Validates: Requirements 5.7, 5.8, 5.9**
    """
    from botocore.exceptions import ClientError as BotoClientError

    namespace, name, system = module_id

    auth_context = {
        "requestContext": {"authorizer": {"permission": permission, "is_master": "false"}}
    }

    if method == "GET_versions":
        event = {
            **auth_context,
            "httpMethod": "GET",
            "path": f"/v1/modules/{namespace}/{name}/{system}/versions",
        }
    elif method == "GET_download":
        event = {
            **auth_context,
            "httpMethod": "GET",
            "path": f"/v1/modules/{namespace}/{name}/{system}/{version}/download",
        }
    else:  # PUT_upload
        event = {
            **auth_context,
            "httpMethod": "PUT",
            "path": f"/v1/modules/{namespace}/{name}/{system}/{version}",
            "body": "dGVzdA==",
            "isBase64Encoded": True,
        }

    # Mock S3 so handlers can execute without real AWS calls
    mock_client = MagicMock()

    if method == "GET_versions":
        mock_paginator = MagicMock()
        mock_paginator.paginate.return_value = [
            {"Contents": [{"Key": f"{namespace}/{name}/{system}/1.0.0/{name}-{system}-1.0.0.zip"}]}
        ]
        mock_client.get_paginator.return_value = mock_paginator
    elif method == "GET_download":
        mock_client.head_object.return_value = {}
        mock_client.generate_presigned_url.return_value = "https://example.com/presigned"
        mock_client.exceptions = MagicMock()
    else:  # PUT_upload
        mock_client.head_object.side_effect = BotoClientError(
            {"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject"
        )
        mock_client.exceptions.ClientError = BotoClientError
        mock_client.put_object.return_value = {}

    with patch.dict(os.environ, {"MODULES_BUCKET": "test-bucket", "TOKEN_TABLE_NAME": "test-tokens"}):
        import s3_client
        old_client = s3_client._s3_client
        s3_client._s3_client = mock_client
        try:
            import handler
            response = handler.handler(event, None)

            if method.startswith("GET"):
                # Both downloader and uploader should be allowed for GET
                assert response["statusCode"] != 403, (
                    f"Expected {permission} to be allowed for GET, got 403"
                )
            else:  # PUT_upload
                if permission == "downloader":
                    assert response["statusCode"] == 403, (
                        f"Expected 403 for downloader PUT, got {response['statusCode']}"
                    )
                    body = json.loads(response["body"])
                    assert body["error"] == "forbidden"
                else:  # uploader
                    assert response["statusCode"] != 403, (
                        f"Expected uploader to be allowed for PUT, got 403"
                    )
        finally:
            s3_client._s3_client = old_client
