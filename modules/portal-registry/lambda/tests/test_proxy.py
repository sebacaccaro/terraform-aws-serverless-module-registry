"""Unit tests for proxy module — fetch_from_public_registry."""

import sys
import os
from unittest.mock import patch, MagicMock
from io import BytesIO
import urllib.error

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from proxy import fetch_from_public_registry, UpstreamNotFoundError, UpstreamError


class TestFetchFromPublicRegistry:
    """Tests for the two-step public registry fetch."""

    def _mock_urlopen_two_step(self, archive_url, archive_bytes):
        """Create a side_effect for urlopen that handles both steps.

        Step 1 (download endpoint): returns response with X-Terraform-Get header.
        Step 2 (archive URL): returns the archive bytes.
        """
        call_count = 0

        def side_effect(req, timeout=None):
            nonlocal call_count
            call_count += 1
            mock_resp = MagicMock()
            if call_count == 1:
                # Step 1: download endpoint returns X-Terraform-Get header
                mock_resp.getheader.side_effect = lambda h: archive_url if h == "X-Terraform-Get" else None
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
            else:
                # Step 2: archive download returns bytes
                mock_resp.read.return_value = archive_bytes
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
            return mock_resp

        return side_effect

    def test_successful_two_step_fetch(self):
        """Successful fetch: step 1 gets archive URL, step 2 downloads bytes."""
        archive_url = "https://releases.hashicorp.com/consul/1.0.0/consul-aws-1.0.0.zip"
        archive_bytes = b"fake-zip-content-here"

        with patch("proxy.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = self._mock_urlopen_two_step(archive_url, archive_bytes)

            result = fetch_from_public_registry("hashicorp", "consul", "aws", "1.0.0")

            assert result == archive_bytes
            assert mock_urlopen.call_count == 2

    def test_404_raises_upstream_not_found_error(self):
        """404 from the download endpoint raises UpstreamNotFoundError."""
        with patch("proxy.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://registry.terraform.io/v1/modules/hashicorp/consul/aws/9.9.9/download",
                code=404,
                msg="Not Found",
                hdrs={},
                fp=BytesIO(b""),
            )

            with pytest.raises(UpstreamNotFoundError) as exc_info:
                fetch_from_public_registry("hashicorp", "consul", "aws", "9.9.9")

            assert "not found" in str(exc_info.value).lower()

    def test_network_error_raises_upstream_error(self):
        """Network failure (URLError) raises UpstreamError."""
        with patch("proxy.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.URLError("Connection refused")

            with pytest.raises(UpstreamError) as exc_info:
                fetch_from_public_registry("hashicorp", "consul", "aws", "1.0.0")

            assert "Failed to reach public registry" in str(exc_info.value)

    def test_non_204_from_download_endpoint_raises_upstream_error(self):
        """Non-404 HTTP error from the download endpoint raises UpstreamError."""
        with patch("proxy.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = urllib.error.HTTPError(
                url="https://registry.terraform.io/v1/modules/hashicorp/consul/aws/1.0.0/download",
                code=500,
                msg="Internal Server Error",
                hdrs={},
                fp=BytesIO(b""),
            )

            with pytest.raises(UpstreamError) as exc_info:
                fetch_from_public_registry("hashicorp", "consul", "aws", "1.0.0")

            assert "HTTP 500" in str(exc_info.value)

    def test_archive_download_failure_raises_upstream_error(self):
        """HTTP error during step 2 (archive download) raises UpstreamError."""
        archive_url = "https://releases.hashicorp.com/consul/1.0.0/consul-aws-1.0.0.zip"
        call_count = 0

        def side_effect(req, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Step 1 succeeds
                mock_resp = MagicMock()
                mock_resp.getheader.side_effect = lambda h: archive_url if h == "X-Terraform-Get" else None
                mock_resp.__enter__ = lambda s: s
                mock_resp.__exit__ = MagicMock(return_value=False)
                return mock_resp
            else:
                # Step 2 fails
                raise urllib.error.HTTPError(
                    url=archive_url,
                    code=503,
                    msg="Service Unavailable",
                    hdrs={},
                    fp=BytesIO(b""),
                )

        with patch("proxy.urllib.request.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = side_effect

            with pytest.raises(UpstreamError) as exc_info:
                fetch_from_public_registry("hashicorp", "consul", "aws", "1.0.0")

            assert "HTTP 503" in str(exc_info.value)
