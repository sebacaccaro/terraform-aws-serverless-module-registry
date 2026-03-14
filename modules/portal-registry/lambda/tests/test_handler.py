"""Unit tests for cache_version handler in handler.py."""

import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handler import handler
from proxy import UpstreamNotFoundError, UpstreamError


def _make_event(method, path, permission="master"):
    """Build a minimal API Gateway proxy event."""
    return {
        "httpMethod": method,
        "path": path,
        "requestContext": {
            "authorizer": {"permission": permission},
        },
    }


class TestCacheVersionSuccess:
    """Test successful cache returns 201 with correct body."""

    @patch("handler.fetch_from_public_registry")
    @patch("handler.s3_client")
    def test_returns_201_with_module_info(self, mock_s3, mock_fetch):
        mock_s3.head_object.return_value = False
        mock_fetch.return_value = b"archive-bytes"

        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/1.0.0")
        resp = handler(event, None)

        assert resp["statusCode"] == 201
        body = json.loads(resp["body"])
        assert body == {
            "namespace": "hashicorp",
            "name": "consul",
            "system": "aws",
            "version": "1.0.0",
        }
        mock_s3.put_object.assert_called_once()
        mock_fetch.assert_called_once_with("hashicorp", "consul", "aws", "1.0.0")


class TestCacheVersionConflict:
    """Test 409 when version already exists locally."""

    @patch("handler.s3_client")
    def test_returns_409_when_version_exists(self, mock_s3):
        mock_s3.head_object.return_value = True

        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/1.0.0")
        resp = handler(event, None)

        assert resp["statusCode"] == 409
        body = json.loads(resp["body"])
        assert body["error"] == "conflict"


class TestCacheVersionUpstreamNotFound:
    """Test 404 when version not found upstream."""

    @patch("handler.fetch_from_public_registry")
    @patch("handler.s3_client")
    def test_returns_404_when_not_found_upstream(self, mock_s3, mock_fetch):
        mock_s3.head_object.return_value = False
        mock_fetch.side_effect = UpstreamNotFoundError("not found")

        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/9.9.9")
        resp = handler(event, None)

        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"] == "not_found"


class TestCacheVersionUpstreamError:
    """Test 502 when upstream is unreachable."""

    @patch("handler.fetch_from_public_registry")
    @patch("handler.s3_client")
    def test_returns_502_on_upstream_error(self, mock_s3, mock_fetch):
        mock_s3.head_object.return_value = False
        mock_fetch.side_effect = UpstreamError("connection refused")

        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/1.0.0")
        resp = handler(event, None)

        assert resp["statusCode"] == 502
        body = json.loads(resp["body"])
        assert body["error"] == "bad_gateway"


class TestCacheVersionValidation:
    """Test 400 for invalid path params and invalid semver."""

    def test_returns_400_for_invalid_namespace(self):
        event = _make_event("POST", "/v1/pins/INVALID!/consul/aws/1.0.0")
        resp = handler(event, None)

        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "invalid_parameter"

    def test_returns_400_for_invalid_name(self):
        event = _make_event("POST", "/v1/pins/hashicorp/BAD NAME/aws/1.0.0")
        resp = handler(event, None)

        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "invalid_parameter"

    def test_returns_400_for_invalid_system(self):
        event = _make_event("POST", "/v1/pins/hashicorp/consul/AWS!!/1.0.0")
        resp = handler(event, None)

        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "invalid_parameter"

    def test_returns_400_for_invalid_semver(self):
        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/not-a-version")
        resp = handler(event, None)

        assert resp["statusCode"] == 400
        body = json.loads(resp["body"])
        assert body["error"] == "invalid_version"


class TestCacheVersionPermission:
    """Test 403 for non-master token."""

    def test_returns_403_for_downloader_token(self):
        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/1.0.0", permission="downloader")
        resp = handler(event, None)

        assert resp["statusCode"] == 403
        body = json.loads(resp["body"])
        assert body["error"] == "forbidden"

    def test_returns_403_for_uploader_token(self):
        event = _make_event("POST", "/v1/pins/hashicorp/consul/aws/1.0.0", permission="uploader")
        resp = handler(event, None)

        assert resp["statusCode"] == 403
        body = json.loads(resp["body"])
        assert body["error"] == "forbidden"


# --- Proxy blocking tests for download_version (Task 5.2) ---


class TestDownloadVersionProxiesWhenNoLocalVersions:
    """Test that download proxies when no local versions exist."""

    @patch("handler.proxy_request")
    @patch("handler.should_proxy", return_value=True)
    @patch("handler._get_proxy_config", return_value={"enabled": True, "allow_list": [], "deny_list": []})
    @patch("handler.s3_client")
    def test_proxies_when_no_local_versions(self, mock_s3, mock_config, mock_should, mock_proxy):
        mock_s3.head_object.return_value = False
        mock_s3.has_local_versions.return_value = False
        mock_proxy.return_value = {
            "statusCode": 204,
            "headers": {"X-Terraform-Get": "https://example.com/archive.zip"},
            "body": "",
        }

        event = _make_event("GET", "/v1/modules/hashicorp/consul/aws/1.0.0/download")
        resp = handler(event, None)

        assert resp["statusCode"] == 204
        mock_proxy.assert_called_once()
        mock_s3.has_local_versions.assert_called_once()


class TestDownloadVersionBlocksProxyWhenLocalVersionsExist:
    """Test that download returns 404 (no proxy) when other local versions exist but requested version does not."""

    @patch("handler.proxy_request")
    @patch("handler.s3_client")
    def test_returns_404_without_proxying(self, mock_s3, mock_proxy):
        mock_s3.head_object.return_value = False
        mock_s3.has_local_versions.return_value = True

        event = _make_event("GET", "/v1/modules/hashicorp/consul/aws/2.0.0/download")
        resp = handler(event, None)

        assert resp["statusCode"] == 404
        body = json.loads(resp["body"])
        assert body["error"] == "not_found"
        mock_proxy.assert_not_called()


class TestDownloadVersionServesLocalVersion:
    """Test that download still works normally when the specific version exists locally."""

    @patch("handler.s3_client")
    def test_returns_204_with_presigned_url(self, mock_s3):
        mock_s3.head_object.return_value = True
        mock_s3.get_presigned_url.return_value = "https://s3.example.com/presigned"

        event = _make_event("GET", "/v1/modules/hashicorp/consul/aws/1.0.0/download")
        resp = handler(event, None)

        assert resp["statusCode"] == 204
        assert resp["headers"]["X-Terraform-Get"] == "https://s3.example.com/presigned"
        # has_local_versions should NOT be called when version exists locally
        mock_s3.has_local_versions.assert_not_called()
