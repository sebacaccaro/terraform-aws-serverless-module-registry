"""
Unit tests for the module-release-prep feature.

These tests verify specific structural and content requirements for the
Portal Terraform module's public release preparation.

Validates: Requirements 2.1–2.9, 9.1–9.5
"""

import os
import glob

import hcl2

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR = os.path.join(os.path.dirname(__file__), "..")
README_PATH = os.path.join(ROOT_DIR, "README.md")
MAIN_TF = os.path.join(ROOT_DIR, "main.tf")
PROVIDERS_TF = os.path.join(ROOT_DIR, "providers.tf")
GITIGNORE_PATH = os.path.join(ROOT_DIR, ".gitignore")


def _read_file(path):
    with open(path, "r") as f:
        return f.read()


def _parse_hcl(path):
    with open(path, "r") as f:
        return hcl2.load(f)


# ---------------------------------------------------------------------------
# README section headings (Requirements 2.1–2.9)
# ---------------------------------------------------------------------------

class TestReadmeSections:
    """Verify required section headings exist in README."""

    def setup_method(self):
        self.readme = _read_file(README_PATH)

    def test_has_features_section(self):
        assert "## Features" in self.readme

    def test_has_prerequisites_section(self):
        assert "## Prerequisites" in self.readme

    def test_has_usage_section(self):
        assert "## Usage" in self.readme

    def test_has_examples_section(self):
        assert "## Examples" in self.readme

    def test_has_inputs_section(self):
        assert "## Inputs" in self.readme

    def test_has_outputs_section(self):
        assert "## Outputs" in self.readme

    def test_has_license_section(self):
        assert "## License" in self.readme


# ---------------------------------------------------------------------------
# README content (Requirements 3.1, 3.4, 6.1)
# ---------------------------------------------------------------------------

class TestReadmeContent:
    """Verify specific content exists in README."""

    def setup_method(self):
        self.readme = _read_file(README_PATH)

    def test_terraformrc_example_exists(self):
        """Requirement 3.1: CLI credentials configuration documented."""
        assert ".terraformrc" in self.readme or "terraform.rc" in self.readme

    def test_token_permission_model_documented(self):
        """Requirement 3.4: Token permission model documented."""
        assert "master" in self.readme
        assert "uploader" in self.readme
        assert "downloader" in self.readme

    def test_api_reference_references_openapi(self):
        """Requirement 6.1: API Reference references openapi.json."""
        assert "openapi.json" in self.readme

    def test_starts_with_module_name_heading(self):
        """Requirement 2.1: README begins with level-1 heading."""
        assert self.readme.startswith("# ")


# ---------------------------------------------------------------------------
# providers.tf structure (Requirement 9.3)
# ---------------------------------------------------------------------------

class TestProvidersTf:
    """Verify providers.tf has no provider {} block."""

    def test_no_provider_block(self):
        """Requirement 9.3: No provider block with profile attribute."""
        content = _read_file(PROVIDERS_TF)
        # Should not contain a provider "aws" { ... } block
        assert 'provider "aws"' not in content, (
            "providers.tf should not contain a provider block"
        )


# ---------------------------------------------------------------------------
# main.tf structure (Requirement 9.5)
# ---------------------------------------------------------------------------

class TestMainTf:
    """Verify main.tf has no module "portal_registry" block."""

    def test_no_module_portal_registry_block(self):
        """Requirement 9.5: No module wrapper block."""
        parsed = _parse_hcl(MAIN_TF)
        for module_block in parsed.get("module", []):
            assert "portal_registry" not in module_block, (
                "main.tf should not contain module \"portal_registry\" block"
            )


# ---------------------------------------------------------------------------
# Cleanup verification (Requirements 9.1, 9.2, 9.5)
# ---------------------------------------------------------------------------

class TestCleanup:
    """Verify boilerplate files have been removed."""

    def test_no_terraform_tfvars(self):
        """Requirement 9.1: No terraform.tfvars at root."""
        assert not os.path.exists(os.path.join(ROOT_DIR, "terraform.tfvars")), (
            "terraform.tfvars should not exist at repository root"
        )

    def test_no_tfstate_files(self):
        """Requirement 9.2: No .tfstate files at root."""
        state_files = glob.glob(os.path.join(ROOT_DIR, "*.tfstate*"))
        assert len(state_files) == 0, (
            f"State files should not exist at root: {state_files}"
        )

    def test_no_modules_portal_registry_directory(self):
        """Requirement 9.5: modules/portal-registry/ directory removed."""
        assert not os.path.isdir(os.path.join(ROOT_DIR, "modules", "portal-registry")), (
            "modules/portal-registry/ directory should not exist"
        )


# ---------------------------------------------------------------------------
# .gitignore entries (Requirement 9.4)
# ---------------------------------------------------------------------------

class TestGitignore:
    """Verify .gitignore covers required patterns."""

    def setup_method(self):
        self.gitignore = _read_file(GITIGNORE_PATH)

    def test_ignores_tfstate(self):
        assert "*.tfstate" in self.gitignore

    def test_ignores_tfstate_backup(self):
        assert "*.tfstate.*" in self.gitignore

    def test_ignores_tfvars(self):
        assert "*.tfvars" in self.gitignore

    def test_ignores_terraform_dir(self):
        assert ".terraform/" in self.gitignore or ".terraform" in self.gitignore
