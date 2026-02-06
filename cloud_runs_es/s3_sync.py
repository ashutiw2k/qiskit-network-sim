#!/usr/bin/env python3
"""Minimal S3 upload/download helper using boto3.

Requires AWS credentials to be available via standard AWS env vars or IAM role.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Tuple


def _require_boto3():
    try:
        import boto3  # type: ignore
    except Exception as exc:
        raise SystemExit(
            "boto3 is required for s3_sync.py. Install it or use the AWS CLI instead."
        ) from exc
    return boto3


def _parse_s3_uri(uri: str) -> Tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ValueError(f"Invalid S3 URI: {uri}")
    path = uri[len("s3://") :]
    parts = path.split("/", 1)
    bucket = parts[0]
    key = parts[1] if len(parts) > 1 else ""
    return bucket, key


def download(s3_uri: str, dest: str) -> None:
    boto3 = _require_boto3()
    bucket, key = _parse_s3_uri(s3_uri)
    if not key:
        raise ValueError("S3 URI must include an object key for download")

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    s3 = boto3.client("s3")
    s3.download_file(bucket, key, dest)
    print(f"Downloaded {s3_uri} -> {dest}")


def upload(src: str, s3_uri: str, recursive: bool) -> None:
    boto3 = _require_boto3()
    bucket, key_prefix = _parse_s3_uri(s3_uri)

    s3 = boto3.client("s3")

    if os.path.isdir(src):
        if not recursive:
            raise ValueError("Source is a directory; use --recursive")
        base = os.path.abspath(src)
        for root, _dirs, files in os.walk(base):
            for fname in files:
                local_path = os.path.join(root, fname)
                rel_path = os.path.relpath(local_path, base)
                key = "/".join(p for p in [key_prefix.rstrip("/"), rel_path] if p)
                s3.upload_file(local_path, bucket, key)
                print(f"Uploaded {local_path} -> s3://{bucket}/{key}")
        return

    if os.path.isfile(src):
        if key_prefix.endswith("/") or key_prefix == "":
            key = "/".join(p for p in [key_prefix.rstrip("/"), os.path.basename(src)] if p)
        else:
            key = key_prefix
        s3.upload_file(src, bucket, key)
        print(f"Uploaded {src} -> s3://{bucket}/{key}")
        return

    raise FileNotFoundError(src)


def main() -> None:
    parser = argparse.ArgumentParser(description="S3 upload/download helper.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="Download from S3")
    d.add_argument("--s3-uri", required=True, help="s3://bucket/key")
    d.add_argument("--dest", required=True, help="Local destination path")

    u = sub.add_parser("upload", help="Upload to S3")
    u.add_argument("--src", required=True, help="Local file or directory")
    u.add_argument("--s3-uri", required=True, help="s3://bucket/key or s3://bucket/prefix/")
    u.add_argument("--recursive", action="store_true", help="Upload directory recursively")

    args = parser.parse_args()

    if args.cmd == "download":
        download(args.s3_uri, args.dest)
    elif args.cmd == "upload":
        upload(args.src, args.s3_uri, args.recursive)
    else:
        raise SystemExit("Unknown command")


if __name__ == "__main__":
    main()
