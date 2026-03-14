"""Input validation functions for path parameters and semver."""

import re

PATH_PARAM_PATTERN = re.compile(r"^[a-z0-9_-]{1,64}$")
SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+$")


class ValidationError(Exception):
    """Custom exception for validation failures.

    Attributes:
        error_code: Machine-readable error code (e.g. 'invalid_parameter').
        message: Human-readable description of the error.
    """

    def __init__(self, error_code, message):
        self.error_code = error_code
        self.message = message
        super().__init__(message)


def validate_path_param(name, value):
    """Validate a path parameter (namespace, name, or system).

    Args:
        name: Parameter name used in error messages (e.g. "namespace").
        value: The parameter value to validate.

    Raises:
        ValidationError: If value doesn't match ^[a-z0-9_-]{1,64}$.
    """
    if not PATH_PARAM_PATTERN.match(value):
        raise ValidationError(
            "invalid_parameter",
            f"Invalid {name}: '{value}'. Must be 1-64 lowercase alphanumeric characters, hyphens, or underscores.",
        )


def validate_semver(version):
    """Validate a semantic version string (X.Y.Z).

    Args:
        version: The version string to validate.

    Raises:
        ValidationError: If version doesn't match ^\\d+\\.\\d+\\.\\d+$.
    """
    if not SEMVER_PATTERN.match(version):
        raise ValidationError(
            "invalid_version",
            f"Version '{version}' is not valid semantic versioning (expected format: X.Y.Z)",
        )
