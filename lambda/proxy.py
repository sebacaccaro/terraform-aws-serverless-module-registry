"""Public registry proxy for forwarding requests to registry.terraform.io."""

import json
import re
import urllib.request
import urllib.error

PUBLIC_REGISTRY_BASE = "https://registry.terraform.io"
PROXY_TIMEOUT = 10


def should_proxy(namespace, name, config):
    """Evaluate allow/deny prefix lists to decide if a module should be proxied.

    The deny list always takes precedence over the allow list.

    Args:
        namespace: Module namespace.
        name: Module name.
        config: Dict with keys 'allow_list' (list[str]) and 'deny_list' (list[str]).

    Returns:
        True if the module should be proxied, False otherwise.
    """
    module_path = f"{namespace}/{name}"
    deny_list = config.get("deny_list", [])
    allow_list = config.get("allow_list", [])

    # Deny list takes precedence
    for prefix in deny_list:
        if module_path.startswith(prefix):
            return False

    # If no allow list, allow all
    if not allow_list:
        return True

    # Must match at least one allow prefix
    for prefix in allow_list:
        if module_path.startswith(prefix):
            return True

    return False


class UpstreamNotFoundError(Exception):
    """Raised when the requested module version is not found on the public registry."""
    pass


class UpstreamError(Exception):
    """Raised when the public registry returns an unexpected error."""
    pass


def _resolve_archive_url(url):
    """Convert a Terraform X-Terraform-Get URL to a downloadable archive URL.

    Handles git:: prefixed GitHub URLs by converting them to tarball downloads.
    E.g. git::https://github.com/org/repo?ref=abc123 -> https://github.com/org/repo/archive/abc123.tar.gz
    """
    if url.startswith("git::"):
        url = url[len("git::"):]
        match = re.match(r'^(https://github\.com/[^?]+)\?ref=(.+)$', url)
        if match:
            return f"{match.group(1)}/archive/{match.group(2)}.tar.gz"
    return url


def fetch_from_public_registry(namespace, name, system, version):
    """Fetch a module archive from the public Terraform registry.

    Performs a two-step fetch:
    1. GET the download endpoint to obtain the X-Terraform-Get header (archive URL).
    2. GET the archive URL to download the actual archive bytes.

    Args:
        namespace: Module namespace.
        name: Module name.
        system: Module system/provider.
        version: Module version (semver).

    Returns:
        bytes: The module archive content.

    Raises:
        UpstreamNotFoundError: If the version doesn't exist on the public registry (404).
        UpstreamError: If the public registry is unreachable or returns an error.
    """
    download_url = f"{PUBLIC_REGISTRY_BASE}/v1/modules/{namespace}/{name}/{system}/{version}/download"
    try:
        req = urllib.request.Request(download_url)
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
            archive_url = resp.getheader("X-Terraform-Get")
            if not archive_url:
                raise UpstreamError(
                    f"Public registry did not return X-Terraform-Get header for {namespace}/{name}/{system}/{version}"
                )
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise UpstreamNotFoundError(
                f"Module {namespace}/{name}/{system} version {version} not found on public registry"
            )
        raise UpstreamError(
            f"Public registry returned HTTP {e.code} for {namespace}/{name}/{system}/{version}"
        )
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise UpstreamError(
            f"Failed to reach public registry: {e}"
        )

    # Step 2: Resolve the archive URL (handle git:: prefix for GitHub repos)
    archive_url = _resolve_archive_url(archive_url)

    try:
        req = urllib.request.Request(archive_url)
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        raise UpstreamError(
            f"Failed to download archive from {archive_url}: HTTP {e.code}"
        )
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise UpstreamError(
            f"Failed to download archive from {archive_url}: {e}"
        )



def proxy_request(path):
    """Forward a request to the public Terraform registry.

    Args:
        path: The request path to forward (e.g. /v1/modules/hashicorp/consul/aws/versions).

    Returns:
        Dict with 'statusCode', 'headers', and 'body' from the public registry,
        or a 502 error response on failure.
    """
    url = f"{PUBLIC_REGISTRY_BASE}{path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=PROXY_TIMEOUT) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
            if 200 <= status < 300:
                # Forward relevant upstream headers
                headers = {"Content-Type": "application/json"}
                for hdr in ("X-Terraform-Get", "Content-Type"):
                    val = resp.getheader(hdr)
                    if val:
                        headers[hdr] = val
                return {
                    "statusCode": status,
                    "headers": headers,
                    "body": body,
                }
            else:
                return {
                    "statusCode": 502,
                    "headers": {"Content-Type": "application/json"},
                    "body": json.dumps({
                        "error": "bad_gateway",
                        "message": f"Failed to proxy request to public registry: upstream returned {status}",
                    }),
                }
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
        return {
            "statusCode": 502,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": "bad_gateway",
                "message": f"Failed to proxy request to public registry: {e}",
            }),
        }
