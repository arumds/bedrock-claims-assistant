"""Step 2.2 - Document storage (Amazon S3).

Thin wrapper over S3. In MOCK_MODE it writes to ./.local_s3/<bucket>/ instead,
so the rest of the pipeline is identical online and offline.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import config  # noqa: E402


class DocumentStore:
    """Read and write claim documents and results in S3 (or a local folder in MOCK_MODE)."""
    def __init__(self, bucket: str = config.BUCKET, mock: bool = config.MOCK_MODE):
        self.bucket = bucket
        self.mock = mock
        if mock:
            self.root = config.LOCAL_STORE_DIR / bucket
            self.root.mkdir(parents=True, exist_ok=True)
            if not any(self.root.rglob("*.*")):
                self._seed_samples()
        else:
            import boto3
            self.s3 = boto3.client("s3", region_name=config.REGION)

    def _seed_samples(self) -> None:
        """MOCK_MODE convenience: fill empty local storage with sample_data/ so every script just works."""
        for sub, prefix in (("claims", config.CLAIMS_PREFIX), ("policies", config.POLICIES_PREFIX)):
            for f in sorted((config.SAMPLE_DIR / sub).glob("*.*")):
                self.upload_file(f, prefix + f.name)
        print(f"[MOCK] Local storage was empty - loaded sample_data/ into {self.root}")

    def upload_file(self, local_path: str | Path, key: str) -> str:
        """Upload a local file to the given key with server-side encryption."""
        local_path = Path(local_path)
        if self.mock:
            dest = self.root / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(local_path.read_bytes())
        else:
            self.s3.upload_file(str(local_path), self.bucket, key,
                                ExtraArgs={"ServerSideEncryption": "AES256"})
        return f"s3://{self.bucket}/{key}"

    def put_json(self, key: str, data: dict) -> str:
        """Write a dict as JSON to the given key."""
        body = json.dumps(data, indent=2, default=str).encode()
        if self.mock:
            dest = self.root / key
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(body)
        else:
            self.s3.put_object(Bucket=self.bucket, Key=key, Body=body,
                               ContentType="application/json",
                               ServerSideEncryption="AES256")
        return f"s3://{self.bucket}/{key}"

    def get_bytes(self, key: str) -> bytes:
        """Read an object's bytes."""
        if self.mock:
            return (self.root / key).read_bytes()
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def list_keys(self, prefix: str = "") -> list[str]:
        """List object keys under a prefix."""
        if self.mock:
            base = self.root / prefix if prefix else self.root
            if not base.exists():
                return []
            return sorted(str(p.relative_to(self.root)) for p in base.rglob("*") if p.is_file())
        keys = []
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=prefix):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return keys
