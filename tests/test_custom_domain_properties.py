"""
Property-based tests for custom domain support in the Portal module.

These tests parse the HCL configuration and verify structural properties
of the aws_api_gateway_domain_name.custom resource.
"""

import os
import hcl2
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
MAIN_TF = os.path.join(ROOT_DIR, "main.tf")


def _parse_main_tf():
    """Parse the portal-registry main.tf and return the full HCL dict."""
    with open(MAIN_TF, "r") as f:
        return hcl2.load(f)


def _find_resource(parsed, resource_type, resource_name):
    """Find a specific resource block in parsed HCL."""
    for resource_block in parsed.get("resource", []):
        if resource_type in resource_block:
            instances = resource_block[resource_type]
            if resource_name in instances:
                return instances[resource_name]
    return None


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

# Generate valid domain names: label.tld
_domain_names = st.from_regex(r"[a-z][a-z0-9\-]{0,20}\.[a-z]{2,6}", fullmatch=True)

# Generate valid ACM certificate ARNs
_certificate_arns = st.from_regex(
    r"arn:aws:acm:us-east-1:[0-9]{12}:certificate/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}",
    fullmatch=True,
)


# ---------------------------------------------------------------------------
# Property 1: Custom domain resource references input variables
# **Validates: Requirements 2.1**
# ---------------------------------------------------------------------------


@given(domain_name=_domain_names, certificate_arn=_certificate_arns)
@settings(max_examples=100)
def test_property1_custom_domain_resource_references_input_variables(
    domain_name: str, certificate_arn: str
):
    """
    **Validates: Requirements 2.1**

    For any valid domain_name and certificate_arn input pair, the
    aws_api_gateway_domain_name.custom resource SHALL reference the
    var.domain_name and var.certificate_arn input variables (not hardcoded
    values), and SHALL use a REGIONAL endpoint configuration.

    The generated domain_name and certificate_arn values serve as witnesses
    that the HCL is parameterised: because the resource attributes contain
    variable references rather than literals, no generated value will appear
    verbatim in the HCL — proving the configuration is properly variable-driven.
    """
    parsed = _parse_main_tf()
    resource = _find_resource(parsed, "aws_api_gateway_domain_name", "custom")

    assert resource is not None, "aws_api_gateway_domain_name.custom resource not found"

    # domain_name attribute must reference var.domain_name, not a hardcoded value
    assert resource["domain_name"] == "${var.domain_name}", (
        f"domain_name should reference var.domain_name, got: {resource['domain_name']}"
    )
    assert domain_name not in resource["domain_name"], (
        "domain_name attribute should not contain a hardcoded value"
    )

    # regional_certificate_arn must reference var.certificate_arn
    assert resource["regional_certificate_arn"] == "${var.certificate_arn}", (
        f"regional_certificate_arn should reference var.certificate_arn, "
        f"got: {resource['regional_certificate_arn']}"
    )
    assert certificate_arn not in resource["regional_certificate_arn"], (
        "regional_certificate_arn attribute should not contain a hardcoded value"
    )

    # endpoint_configuration must be REGIONAL
    endpoint_config = resource.get("endpoint_configuration")
    assert endpoint_config is not None, "endpoint_configuration block is missing"
    # hcl2 parses blocks as a list of dicts
    assert isinstance(endpoint_config, list) and len(endpoint_config) > 0, (
        "endpoint_configuration should be a non-empty list"
    )
    types = endpoint_config[0].get("types")
    assert types == ["REGIONAL"], (
        f"endpoint_configuration types should be ['REGIONAL'], got: {types}"
    )


# ---------------------------------------------------------------------------
# Helpers for variables.tf parsing
# ---------------------------------------------------------------------------

VARIABLES_TF = os.path.join(ROOT_DIR, "variables.tf")


def _parse_variables_tf():
    """Parse the portal-registry variables.tf and return the full HCL dict."""
    with open(VARIABLES_TF, "r") as f:
        return hcl2.load(f)


def _get_variable_block(parsed, var_name):
    """Find a specific variable block by name in parsed HCL."""
    for var_block in parsed.get("variable", []):
        if var_name in var_block:
            return var_block[var_name]
    return None


# ---------------------------------------------------------------------------
# Pre-existing variables fixture for Property 2
# ---------------------------------------------------------------------------

PRE_EXISTING_VARIABLES = {
    "proxy_enabled": {"type": "bool", "default": False},
    "proxy_allow_list": {"type": "${list(string)}", "default": []},
    "proxy_deny_list": {"type": "${list(string)}", "default": []},
    "s3_bucket_name": {"type": "string", "default": ""},
    "token_table_name": {"type": "string", "default": "portal-tokens"},
    "master_token_secret_name": {"type": "string", "default": "prtl-master-token"},
}


# ---------------------------------------------------------------------------
# Property 2: Existing input variables are preserved
# **Validates: Requirements 4.1**
# ---------------------------------------------------------------------------

_pre_existing_var_names = st.sampled_from(list(PRE_EXISTING_VARIABLES.keys()))


@given(var_name=_pre_existing_var_names)
@settings(max_examples=100)
def test_property2_existing_input_variables_are_preserved(var_name: str):
    """
    **Validates: Requirements 4.1**

    For any input variable that existed before this feature was added,
    its name, type, and default value SHALL remain identical in the
    updated module variables.tf.
    """
    parsed = _parse_variables_tf()
    var_block = _get_variable_block(parsed, var_name)

    expected = PRE_EXISTING_VARIABLES[var_name]

    # Variable must still exist
    assert var_block is not None, (
        f"Pre-existing variable '{var_name}' is missing from variables.tf"
    )

    # Type must be preserved
    assert var_block.get("type") == expected["type"], (
        f"Variable '{var_name}' type changed: "
        f"expected {expected['type']!r}, got {var_block.get('type')!r}"
    )

    # Default must be preserved
    assert var_block.get("default") == expected["default"], (
        f"Variable '{var_name}' default changed: "
        f"expected {expected['default']!r}, got {var_block.get('default')!r}"
    )


# ---------------------------------------------------------------------------
# Helpers for outputs.tf parsing
# ---------------------------------------------------------------------------

OUTPUTS_TF = os.path.join(ROOT_DIR, "outputs.tf")


def _parse_outputs_tf():
    """Parse the portal-registry outputs.tf and return the full HCL dict."""
    with open(OUTPUTS_TF, "r") as f:
        return hcl2.load(f)


def _get_output_block(parsed, output_name):
    """Find a specific output block by name in parsed HCL."""
    for out_block in parsed.get("output", []):
        if output_name in out_block:
            return out_block[output_name]
    return None


# ---------------------------------------------------------------------------
# Pre-existing outputs fixture for Property 3
# ---------------------------------------------------------------------------

PRE_EXISTING_OUTPUTS = {
    "api_endpoint": "${aws_api_gateway_stage.main.invoke_url}",
    "api_id": "${aws_api_gateway_rest_api.main.id}",
    "s3_bucket_name": "${aws_s3_bucket.modules.id}",
    "s3_bucket_arn": "${aws_s3_bucket.modules.arn}",
    "dynamodb_table_name": "${aws_dynamodb_table.tokens.name}",
    "master_token_secret_arn": "${aws_secretsmanager_secret.master_token.arn}",
}


# ---------------------------------------------------------------------------
# Property 3: Existing outputs are preserved
# **Validates: Requirements 4.2**
# ---------------------------------------------------------------------------

_pre_existing_output_names = st.sampled_from(list(PRE_EXISTING_OUTPUTS.keys()))


@given(output_name=_pre_existing_output_names)
@settings(max_examples=100)
def test_property3_existing_outputs_are_preserved(output_name: str):
    """
    **Validates: Requirements 4.2**

    For any output that existed before this feature was added, its name
    and value expression SHALL remain identical in the updated module
    outputs.tf.
    """
    parsed = _parse_outputs_tf()
    out_block = _get_output_block(parsed, output_name)

    expected_value = PRE_EXISTING_OUTPUTS[output_name]

    # Output must still exist
    assert out_block is not None, (
        f"Pre-existing output '{output_name}' is missing from outputs.tf"
    )

    # Value expression must be preserved
    assert out_block.get("value") == expected_value, (
        f"Output '{output_name}' value changed: "
        f"expected {expected_value!r}, got {out_block.get('value')!r}"
    )


# ---------------------------------------------------------------------------
# Property 4: Service discovery URL uses custom domain
# **Validates: Requirements 4.3, 5.1**
# ---------------------------------------------------------------------------


@given(domain_name=_domain_names)
@settings(max_examples=100)
def test_property4_service_discovery_url_uses_custom_domain(domain_name: str):
    """
    **Validates: Requirements 4.3, 5.1**

    For any valid domain_name input, the .well-known/terraform.json S3
    object content SHALL contain the modules.v1 URL using
    https://<domain_name>/v1/modules/ where <domain_name> comes from
    var.domain_name (not a hardcoded literal).

    The generated domain_name values serve as witnesses that the HCL
    content expression is parameterised via var.domain_name.
    """
    parsed = _parse_main_tf()
    resource = _find_resource(parsed, "aws_s3_object", "terraform_json")

    assert resource is not None, "aws_s3_object.terraform_json resource not found"

    content = resource.get("content", "")

    # The content must reference var.domain_name
    assert "var.domain_name" in content, (
        f"terraform_json content should reference var.domain_name, got: {content}"
    )

    # The content must build the correct URL pattern
    assert "https://${var.domain_name}/v1/modules/" in content, (
        f"terraform_json content should use https://${{var.domain_name}}/v1/modules/, got: {content}"
    )

    # The content must include modules.v1 key
    assert "modules.v1" in content, (
        f"terraform_json content should include modules.v1 key, got: {content}"
    )

    # The generated domain name should NOT appear literally (proving parameterisation)
    assert domain_name not in content, (
        f"terraform_json content should not contain hardcoded domain '{domain_name}'"
    )
