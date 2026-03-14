"""Unit tests for validators module."""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from validators import ValidationError, validate_path_param, validate_semver


class TestValidationError:
    def test_has_error_code_and_message(self):
        err = ValidationError("invalid_parameter", "bad input")
        assert err.error_code == "invalid_parameter"
        assert err.message == "bad input"

    def test_is_exception(self):
        err = ValidationError("code", "msg")
        assert isinstance(err, Exception)
        assert str(err) == "msg"


class TestValidatePathParam:
    def test_valid_lowercase(self):
        validate_path_param("namespace", "myorg")

    def test_valid_with_hyphens(self):
        validate_path_param("name", "my-module")

    def test_valid_with_underscores(self):
        validate_path_param("system", "my_system")

    def test_valid_with_digits(self):
        validate_path_param("namespace", "org123")

    def test_valid_single_char(self):
        validate_path_param("name", "a")

    def test_valid_max_length(self):
        validate_path_param("namespace", "a" * 64)

    def test_invalid_uppercase(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_path_param("namespace", "MyOrg")
        assert exc_info.value.error_code == "invalid_parameter"
        assert "namespace" in exc_info.value.message

    def test_invalid_empty(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_path_param("name", "")
        assert exc_info.value.error_code == "invalid_parameter"

    def test_invalid_too_long(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_path_param("system", "a" * 65)
        assert exc_info.value.error_code == "invalid_parameter"

    def test_invalid_special_chars(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_path_param("namespace", "my.org")
        assert exc_info.value.error_code == "invalid_parameter"

    def test_invalid_spaces(self):
        with pytest.raises(ValidationError):
            validate_path_param("name", "my module")

    def test_error_message_identifies_parameter(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_path_param("system", "INVALID!")
        assert "system" in exc_info.value.message


class TestValidateSemver:
    def test_valid_simple(self):
        validate_semver("1.0.0")

    def test_valid_zeros(self):
        validate_semver("0.0.0")

    def test_valid_large_numbers(self):
        validate_semver("100.200.300")

    def test_invalid_missing_patch(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_semver("1.0")
        assert exc_info.value.error_code == "invalid_version"

    def test_invalid_text(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_semver("abc")
        assert exc_info.value.error_code == "invalid_version"
        assert "abc" in exc_info.value.message

    def test_invalid_prerelease(self):
        with pytest.raises(ValidationError):
            validate_semver("1.0.0-beta")

    def test_invalid_leading_v(self):
        with pytest.raises(ValidationError):
            validate_semver("v1.0.0")

    def test_invalid_empty(self):
        with pytest.raises(ValidationError):
            validate_semver("")

    def test_error_message_format(self):
        with pytest.raises(ValidationError) as exc_info:
            validate_semver("bad")
        assert "not valid semantic versioning" in exc_info.value.message
        assert "X.Y.Z" in exc_info.value.message
