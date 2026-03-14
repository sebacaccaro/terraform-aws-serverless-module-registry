"""Unit tests for s3_client module — has_local_versions."""

import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from s3_client import has_local_versions


class TestHasLocalVersions:
    """Tests for has_local_versions prefix check."""

    def test_returns_true_when_objects_exist(self):
        """Returns True when at least one object exists under the prefix."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "KeyCount": 1,
            "Contents": [
                {"Key": "hashicorp/consul/aws/1.0.0/consul-aws-1.0.0.zip"}
            ],
        }

        with patch("s3_client._get_client", return_value=mock_client):
            result = has_local_versions("my-bucket", "hashicorp/consul/aws/")

        assert result is True
        mock_client.list_objects_v2.assert_called_once_with(
            Bucket="my-bucket", Prefix="hashicorp/consul/aws/", MaxKeys=1
        )

    def test_returns_false_when_no_objects_exist(self):
        """Returns False when no objects exist under the prefix."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "KeyCount": 0,
        }

        with patch("s3_client._get_client", return_value=mock_client):
            result = has_local_versions("my-bucket", "hashicorp/consul/aws/")

        assert result is False
        mock_client.list_objects_v2.assert_called_once_with(
            Bucket="my-bucket", Prefix="hashicorp/consul/aws/", MaxKeys=1
        )
