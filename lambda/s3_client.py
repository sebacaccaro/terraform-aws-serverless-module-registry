"""S3 operations wrapper for module storage."""

import re

import boto3

_s3_client = None


def _get_client():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3")
    return _s3_client


def list_versions(bucket, prefix):
    """List all unique version strings under a module prefix.

    Paginates through list_objects_v2 and extracts version strings from
    S3 keys matching the pattern {prefix}{version}/...

    Args:
        bucket: S3 bucket name.
        prefix: Key prefix like "{namespace}/{name}/{system}/".

    Returns:
        Sorted list of unique version strings, e.g. ["1.0.0", "1.1.0"].
    """
    client = _get_client()
    versions = set()
    paginator = client.get_paginator("list_objects_v2")

    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            # Strip the prefix and extract the version segment
            remainder = key[len(prefix):]
            parts = remainder.split("/")
            if parts and re.match(r"^\d+\.\d+\.\d+$", parts[0]):
                versions.add(parts[0])

    return sorted(versions)


def get_presigned_url(bucket, key, expiry=300):
    """Generate a presigned S3 URL for downloading a module archive.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        expiry: URL expiration in seconds (default 300 = 5 minutes).

    Returns:
        Presigned URL string.
    """
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=expiry,
    )


def head_object(bucket, key):
    """Check if an object exists in S3.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.

    Returns:
        True if the object exists, False otherwise.
    """
    client = _get_client()
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except client.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        raise


def put_object(bucket, key, body):
    """Upload a module archive to S3.

    Args:
        bucket: S3 bucket name.
        key: S3 object key.
        body: Binary content to upload.
    """
    client = _get_client()
    client.put_object(Bucket=bucket, Key=key, Body=body)

def has_local_versions(bucket, prefix):
    """Check if any objects exist under the given S3 prefix.

    Uses list_objects_v2 with MaxKeys=1 for efficiency.

    Args:
        bucket: S3 bucket name.
        prefix: Key prefix like "{namespace}/{name}/{system}/".

    Returns:
        True if at least one object exists under the prefix.
    """
    client = _get_client()
    resp = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=1)
    return resp.get("KeyCount", 0) > 0
