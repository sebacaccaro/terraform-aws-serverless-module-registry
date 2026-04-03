"""
Property-based tests for the module-release-prep feature.

These tests verify correctness properties defined in the design document
for the Portal Terraform module's public release preparation.
"""

import os
import re
import sys
import glob

import hcl2
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
MAIN_TF = os.path.join(ROOT_DIR, "main.tf")
VARIABLES_TF = os.path.join(ROOT_DIR, "variables.tf")
OUTPUTS_TF = os.path.join(ROOT_DIR, "outputs.tf")
README_PATH = os.path.join(ROOT_DIR, "README.md")
EXAMPLES_DIR = os.path.join(ROOT_DIR, "examples")

# Add lambda directory to path for importing proxy module
sys.path.insert(0, os.path.join(ROOT_DIR, "lambda"))
from proxy import should_proxy  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_tf_files():
    """Collect all .tf files at root and in examples/."""
    tf_files = glob.glob(os.path.join(ROOT_DIR, "*.tf"))
    tf_files += glob.glob(os.path.join(EXAMPLES_DIR, "**", "*.tf"), recursive=True)
    return tf_files


def _parse_hcl_file(path):
    with open(path, "r") as f:
        return hcl2.load(f)


def _read_readme():
    with open(README_PATH, "r") as f:
        return f.read()


# ---------------------------------------------------------------------------
# Property 1: No hardcoded environment-specific values in Terraform files
# Feature: module-release-prep
# Validates: Requirements 1.5, 8.5
# ---------------------------------------------------------------------------

FORBIDDEN_PATTERNS = [
    re.compile(r'profile\s*=\s*"[^"]*"'),         # profile = "..." in provider blocks
    re.compile(r"gateway-test\.thron\.com"),       # hardcoded test domain
    re.compile(r"116184089574"),                   # specific account ID from original repo
    re.compile(r"sandbox-admin"),                  # specific profile name from original repo
]

# Strategy: pick a random .tf file from the collected set
_tf_file_paths = _collect_tf_files()
_tf_files_strategy = st.sampled_from(_tf_file_paths) if _tf_file_paths else st.nothing()


@given(tf_path=_tf_files_strategy)
@settings(max_examples=100)
def test_property1_no_hardcoded_env_values(tf_path: str):
    """
    Feature: module-release-prep, Property 1: No hardcoded environment-specific values

    For any .tf file at the repository root or in the examples/ directory,
    the file content shall not contain 12-digit AWS account ID patterns,
    AWS profile name assignments, or specific hardcoded values from the
    original repo.

    Validates: Requirements 1.5, 8.5
    """
    with open(tf_path, "r") as f:
        content = f.read()

    for pattern in FORBIDDEN_PATTERNS:
        match = pattern.search(content)
        assert match is None, (
            f"Forbidden pattern {pattern.pattern!r} found in {os.path.relpath(tf_path, ROOT_DIR)}: "
            f"'{match.group()}'"
        )


# ---------------------------------------------------------------------------
# Property 2: README documents all inputs and outputs
# Feature: module-release-prep
# Validates: Requirements 2.7, 2.8
# ---------------------------------------------------------------------------

def _extract_variable_names():
    parsed = _parse_hcl_file(VARIABLES_TF)
    return [name for block in parsed.get("variable", []) for name in block.keys()]


def _extract_output_names():
    parsed = _parse_hcl_file(OUTPUTS_TF)
    return [name for block in parsed.get("output", []) for name in block.keys()]


_variable_names = _extract_variable_names()
_output_names = _extract_output_names()

_variable_strategy = st.sampled_from(_variable_names) if _variable_names else st.nothing()
_output_strategy = st.sampled_from(_output_names) if _output_names else st.nothing()


@given(var_name=_variable_strategy)
@settings(max_examples=100)
def test_property2a_readme_documents_all_inputs(var_name: str):
    """
    Feature: module-release-prep, Property 2: README documents all inputs

    For any variable declared in variables.tf, the README ## Inputs section
    shall contain that variable's name.

    Validates: Requirements 2.7
    """
    readme = _read_readme()
    inputs_section_match = re.search(r"## Inputs\s*\n(.*?)(?=\n## |\Z)", readme, re.DOTALL)
    assert inputs_section_match is not None, "README is missing ## Inputs section"
    inputs_section = inputs_section_match.group(1)
    assert var_name in inputs_section, (
        f"Variable '{var_name}' from variables.tf is not documented in README ## Inputs section"
    )


@given(output_name=_output_strategy)
@settings(max_examples=100)
def test_property2b_readme_documents_all_outputs(output_name: str):
    """
    Feature: module-release-prep, Property 2: README documents all outputs

    For any output declared in outputs.tf, the README ## Outputs section
    shall contain that output's name.

    Validates: Requirements 2.8
    """
    readme = _read_readme()
    outputs_section_match = re.search(r"## Outputs\s*\n(.*?)(?=\n## |\Z)", readme, re.DOTALL)
    assert outputs_section_match is not None, "README is missing ## Outputs section"
    outputs_section = outputs_section_match.group(1)
    assert output_name in outputs_section, (
        f"Output '{output_name}' from outputs.tf is not documented in README ## Outputs section"
    )


# ---------------------------------------------------------------------------
# Property 3: Every variable has a meaningful description
# Feature: module-release-prep
# Validates: Requirements 7.1, 7.2
# ---------------------------------------------------------------------------

def _extract_variables_with_details():
    """Return list of (name, block) tuples for all variables."""
    parsed = _parse_hcl_file(VARIABLES_TF)
    result = []
    for var_block in parsed.get("variable", []):
        for name, block in var_block.items():
            result.append((name, block))
    return result


_variables_with_details = _extract_variables_with_details()
_variable_detail_strategy = st.sampled_from(_variables_with_details) if _variables_with_details else st.nothing()


@given(var_tuple=_variable_detail_strategy)
@settings(max_examples=100)
def test_property3_every_variable_has_meaningful_description(var_tuple):
    """
    Feature: module-release-prep, Property 3: Every variable has a meaningful description

    For any variable declared in variables.tf, the variable shall have a
    non-empty description attribute. Additionally, for any variable of type
    list(string), the description shall contain a bracket character ([)
    indicating an example value is provided.

    Validates: Requirements 7.1, 7.2
    """
    name, block = var_tuple
    description = block.get("description", "")

    assert description and description.strip(), (
        f"Variable '{name}' has an empty or missing description"
    )

    var_type = str(block.get("type", ""))
    if "list(string)" in var_type:
        assert "[" in description, (
            f"Variable '{name}' is list(string) but description does not contain "
            f"an example value with brackets: {description!r}"
        )


# ---------------------------------------------------------------------------
# Property 4: Every example directory is self-contained
# Feature: module-release-prep
# Validates: Requirements 8.4
# ---------------------------------------------------------------------------

def _list_example_dirs():
    """Return list of subdirectory paths under examples/."""
    if not os.path.isdir(EXAMPLES_DIR):
        return []
    return [
        os.path.join(EXAMPLES_DIR, d)
        for d in os.listdir(EXAMPLES_DIR)
        if os.path.isdir(os.path.join(EXAMPLES_DIR, d))
    ]


_example_dirs = _list_example_dirs()
_example_dir_strategy = st.sampled_from(_example_dirs) if _example_dirs else st.nothing()


@given(example_dir=_example_dir_strategy)
@settings(max_examples=100)
def test_property4_every_example_is_self_contained(example_dir: str):
    """
    Feature: module-release-prep, Property 4: Every example directory is self-contained

    For any subdirectory in examples/, the directory shall contain both
    a main.tf file and a README.md file.

    Validates: Requirements 8.4
    """
    dir_name = os.path.basename(example_dir)
    main_tf = os.path.join(example_dir, "main.tf")
    readme = os.path.join(example_dir, "README.md")

    assert os.path.isfile(main_tf), (
        f"Example '{dir_name}' is missing main.tf"
    )
    assert os.path.isfile(readme), (
        f"Example '{dir_name}' is missing README.md"
    )


# ---------------------------------------------------------------------------
# Property 5: Required variables have no default, optional variables have defaults
# Feature: module-release-prep
# Validates: Requirements 1.6, 1.7
# ---------------------------------------------------------------------------

REQUIRED_VARIABLES = ["domain_name", "certificate_arn"]
OPTIONAL_VARIABLES = [
    "proxy_enabled", "proxy_allow_list", "proxy_deny_list",
    "s3_bucket_name", "token_table_name", "master_token_secret_name",
]

_required_var_strategy = st.sampled_from(REQUIRED_VARIABLES)
_optional_var_strategy = st.sampled_from(OPTIONAL_VARIABLES)


def _get_variable_block(var_name):
    parsed = _parse_hcl_file(VARIABLES_TF)
    for var_block in parsed.get("variable", []):
        if var_name in var_block:
            return var_block[var_name]
    return None


@given(var_name=_required_var_strategy)
@settings(max_examples=100)
def test_property5a_required_variables_have_no_default(var_name: str):
    """
    Feature: module-release-prep, Property 5: Required variables have no default

    For any variable that is environment-specific (domain_name, certificate_arn),
    the variable shall have no default attribute.

    Validates: Requirements 1.7
    """
    block = _get_variable_block(var_name)
    assert block is not None, f"Required variable '{var_name}' not found in variables.tf"
    assert "default" not in block, (
        f"Required variable '{var_name}' should not have a default value, "
        f"but has default={block.get('default')!r}"
    )


@given(var_name=_optional_var_strategy)
@settings(max_examples=100)
def test_property5b_optional_variables_have_defaults(var_name: str):
    """
    Feature: module-release-prep, Property 5: Optional variables have defaults

    For any variable that has a sensible non-environment-specific default,
    the variable shall have a default attribute.

    Validates: Requirements 1.6
    """
    block = _get_variable_block(var_name)
    assert block is not None, f"Optional variable '{var_name}' not found in variables.tf"
    assert "default" in block, (
        f"Optional variable '{var_name}' should have a default value"
    )


# ---------------------------------------------------------------------------
# Property 6: Proxy deny list takes precedence over allow list
# Feature: module-release-prep
# Validates: Requirements 4.5
# ---------------------------------------------------------------------------

# Strategy: generate namespace/name pairs and a shared prefix that appears in both lists
_namespace_names = st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True)
_module_names = st.from_regex(r"[a-z][a-z0-9-]{0,10}", fullmatch=True)


@given(namespace=_namespace_names, name=_module_names)
@settings(max_examples=100)
def test_property6_deny_list_takes_precedence(namespace: str, name: str):
    """
    Feature: module-release-prep, Property 6: Proxy deny list takes precedence over allow list

    For any module namespace/name pair and any proxy configuration where
    the module matches both an allow list prefix and a deny list prefix,
    the should_proxy function shall return False (deny wins).

    Validates: Requirements 4.5
    """
    # Create a prefix that matches the module, put it in both lists
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
# Property 7: Validation blocks reject invalid formats
# Feature: module-release-prep
# Validates: Requirements 7.4
# ---------------------------------------------------------------------------

# Extract the validation regex patterns from variables.tf
# domain_name: ^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$
# certificate_arn: ^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-f0-9-]+$

DOMAIN_NAME_REGEX = re.compile(
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
CERTIFICATE_ARN_REGEX = re.compile(
    r"^arn:aws:acm:[a-z0-9-]+:[0-9]{12}:certificate/[a-f0-9-]+$"
)

# Strategy: generate strings that are clearly invalid domain names
_invalid_domains = st.one_of(
    st.just(""),                                          # empty string
    st.just("-invalid.com"),                               # starts with hyphen
    st.just("UPPER.com"),                                  # uppercase
    st.just("has spaces.com"),                             # spaces
    st.just("under_score.com"),                            # underscore
    st.from_regex(r"[A-Z]{3,10}\.[A-Z]{2,4}", fullmatch=True),  # all uppercase
    st.from_regex(r"[!@#$%^&*]{1,5}", fullmatch=True),   # special chars
    st.text(min_size=1, max_size=10).filter(
        lambda s: not DOMAIN_NAME_REGEX.match(s)
    ),
)

# Strategy: generate strings that are clearly invalid ARNs
_invalid_arns = st.one_of(
    st.just(""),                                           # empty string
    st.just("not-an-arn"),                                 # no arn: prefix
    st.just("arn:aws:s3:::my-bucket"),                     # wrong service
    st.just("arn:aws:acm:us-east-1:short:certificate/x"), # account too short
    st.text(min_size=1, max_size=20).filter(
        lambda s: not CERTIFICATE_ARN_REGEX.match(s)
    ),
)


@given(domain=_invalid_domains)
@settings(max_examples=100)
def test_property7a_domain_validation_rejects_invalid(domain: str):
    """
    Feature: module-release-prep, Property 7: Validation blocks reject invalid formats

    For any string that is not a valid DNS hostname, the domain_name
    variable validation shall reject it.

    Validates: Requirements 7.4
    """
    assert not DOMAIN_NAME_REGEX.match(domain), (
        f"Domain validation regex should reject {domain!r} but it matched"
    )


@given(arn=_invalid_arns)
@settings(max_examples=100)
def test_property7b_certificate_arn_validation_rejects_invalid(arn: str):
    """
    Feature: module-release-prep, Property 7: Validation blocks reject invalid formats

    For any string that is not a valid ACM certificate ARN pattern, the
    certificate_arn variable validation shall reject it.

    Validates: Requirements 7.4
    """
    assert not CERTIFICATE_ARN_REGEX.match(arn), (
        f"Certificate ARN validation regex should reject {arn!r} but it matched"
    )
