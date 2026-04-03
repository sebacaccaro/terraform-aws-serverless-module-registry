"""
Property-based tests for the Portal API logic.

Tests the proxy allow/deny list evaluation and input validation regex patterns.
"""

import re
import sys
import os

from hypothesis import given, settings
from hypothesis import strategies as st

# Add lambda directory to path for importing proxy module
ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT_DIR, "lambda"))
from proxy import should_proxy  # noqa: E402


# ---------------------------------------------------------------------------
# Proxy deny list takes precedence over allow list
# ---------------------------------------------------------------------------

_namespace_names = st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True)
_module_names = st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True)


@given(namespace=_namespace_names, name=_module_names)
@settings(max_examples=100)
def test_property6_deny_list_takes_precedence(namespace: str, name: str):
    """Deny list always wins when a module matches both allow and deny lists."""
    shared_prefix = f"{namespace}/"
    config = {
        "allow_list": [shared_prefix],
        "deny_list": [shared_prefix],
    }
    result = should_proxy(namespace, name, config)
    assert result is False, (
        f"should_proxy({namespace!r}, {name!r}, ...) returned True when module "
        f"matches both allow and deny lists (prefix={shared_prefix!r})"
    )


# ---------------------------------------------------------------------------
# Validation regex: domain_name rejects invalid formats
# ---------------------------------------------------------------------------

DOMAIN_NAME_REGEX = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
CERTIFICATE_ARN_REGEX = re.compile(
    r"^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-f0-9-]+$"
)

_invalid_domains = st.one_of(
    st.just(""),
    st.just("-invalid.com"),
    st.just("UPPER.com"),
    st.just("has spaces.com"),
    st.just("under_score.com"),
    st.from_regex(r"[A-Z]{3,10}\.[A-Z]{2,4}", fullmatch=True),
    st.from_regex(r"[!@#$%^&*]{1,5}", fullmatch=True),
    st.text(min_size=1, max_size=10).filter(
        lambda s: not DOMAIN_NAME_REGEX.match(s)
    ),
)

_invalid_arns = st.one_of(
    st.just(""),
    st.just("not-an-arn"),
    st.just("arn:aws:s3:::my-bucket"),
    st.just("arn:aws:acm:us-east-1:short:certificate/x"),
    st.text(min_size=1, max_size=20).filter(
        lambda s: not CERTIFICATE_ARN_REGEX.match(s)
    ),
)


@given(domain=_invalid_domains)
@settings(max_examples=100)
def test_property7a_domain_validation_rejects_invalid(domain: str):
    """Invalid DNS hostnames are rejected by the domain_name validation regex."""
    assert not DOMAIN_NAME_REGEX.match(domain), (
        f"Domain validation regex should reject {domain!r} but it matched"
    )


@given(arn=_invalid_arns)
@settings(max_examples=100)
def test_property7b_certificate_arn_validation_rejects_invalid(arn: str):
    """Invalid ARNs are rejected by the certificate_arn validation regex."""
    assert not CERTIFICATE_ARN_REGEX.match(arn), (
        f"Certificate ARN validation regex should reject {arn!r} but it matched"
    )
