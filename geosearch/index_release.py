"""Immutable S3 bundles, selected by one atomic current.json pointer.

Fetch needs only boto3, so image deploys still consume a prebuilt index without loading
FAISS or invoking Bedrock. A missing pointer supports the original flat index prefix.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError


def location(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    prefix = parsed.path.strip("/")
    if parsed.scheme != "s3" or not parsed.netloc or not prefix:
        raise ValueError("Expected s3://bucket/index-prefix")
    return parsed.netloc, prefix


def checksum(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fetch(s3: Any, uri: str, output: Path) -> None:
    bucket, base = location(uri)
    manifest = None
    try:
        manifest = json.loads(
            s3.get_object(Bucket=bucket, Key=f"{base}/current.json")["Body"].read()
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("NoSuchKey", "404"):
            raise
    if manifest is not None:
        prefix = manifest["prefix"]
        if not prefix.startswith(f"{base}/releases/") or not prefix.endswith("/"):
            raise ValueError("Invalid index release prefix")
        files = manifest["files"]
    else:
        prefix = f"{base}/"
        files = {}
        for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix
        ):
            for item in page.get("Contents", []):
                name = item["Key"][len(prefix) :]
                if name and not name.endswith("/") and not name.startswith("releases/"):
                    files[name] = None
    required = {
        "geosearch.duckdb",
        "layer_title.faiss",
        "layer_description.faiss",
        "division_name.faiss",
    }
    if manifest is not None:
        required.add("meta.json")
    if not required.issubset(files) or not any(
        name.startswith("s3/") for name in files
    ):
        raise ValueError("Published index is missing required files or boundaries")
    # Stage first: a broken download cannot mix new vectors with an old database.
    with tempfile.TemporaryDirectory(prefix="sgs-index-") as temporary:
        staging = Path(temporary)
        for name, digest in files.items():
            relative = Path(name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Invalid index bundle path")
            path = staging / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, prefix + name, str(path))
            if not path.stat().st_size or (digest and checksum(path) != digest):
                raise ValueError(f"Empty or corrupt index file: {name}")
        output.mkdir(parents=True, exist_ok=True)
        if "meta.json" not in files:
            (output / "meta.json").unlink(missing_ok=True)
        shutil.copytree(staging, output, dirs_exist_ok=True)


def publish(s3: Any, uri: str, directory: Path) -> str:
    # Only the build/publish job imports the heavier offline validator.
    from .index_metadata import validate_bundle

    metadata = validate_bundle(directory)
    bucket, base = location(uri)
    prefix = f"{base}/releases/{uuid.uuid4().hex}/"
    files = {
        path.relative_to(directory).as_posix(): checksum(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file()
    }
    for name in files:
        s3.upload_file(str(directory / name), bucket, prefix + name)
    # An interrupted upload leaves an unreferenced release. Readers see either the old
    # complete bundle or this complete bundle, never an in-place multi-object sync.
    pointer = {"prefix": prefix, "built_at": metadata["built_at"], "files": files}
    s3.put_object(
        Bucket=bucket,
        Key=f"{base}/current.json",
        Body=json.dumps(pointer).encode(),
        ContentType="application/json",
    )
    return prefix


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "publish"))
    parser.add_argument("--uri", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    client = boto3.client("s3")
    if args.operation == "fetch":
        fetch(client, args.uri, args.directory)
    else:
        print(publish(client, args.uri, args.directory))


if __name__ == "__main__":
    main()
