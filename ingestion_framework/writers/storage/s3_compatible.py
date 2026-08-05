from __future__ import annotations

from pathlib import Path

from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.secrets import resolve_secret_reference
from ingestion_framework.writers.storage.base import BaseStorageWriter


class S3CompatibleStorageWriter(BaseStorageWriter):
    """Writes objects to S3-compatible storage such as MinIO."""

    def __init__(self, config: StorageConfig, client=None) -> None:
        self.config = config
        self.bucket = require_value(config.bucket, "bucket")
        self.base_prefix = (config.base_prefix or "").strip("/")
        self.client = client or self._create_client(config)

    def write_file(self, source_file: str | Path, target_key: str) -> str:
        key = self._object_key(target_key)
        self.client.upload_file(str(source_file), self.bucket, key)
        return self._uri(key)

    def write_bytes(self, content: bytes, target_key: str) -> str:
        key = self._object_key(target_key)
        self.client.put_object(Bucket=self.bucket, Key=key, Body=content)
        return self._uri(key)

    def _object_key(self, target_key: str) -> str:
        cleaned = str(target_key).lstrip("/")
        if self.base_prefix:
            return f"{self.base_prefix}/{cleaned}"
        return cleaned

    def _uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def _create_client(self, config: StorageConfig):
        try:
            import boto3
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "boto3 is required for s3_compatible storage. Install the project "
                "dependencies in the runtime container before using MinIO storage."
            ) from exc

        endpoint_url = require_value(config.endpoint_url, "endpoint_url")
        access_key = resolve_secret_reference(require_value(config.access_key_ref, "access_key_ref"))
        secret_key = resolve_secret_reference(require_value(config.secret_key_ref, "secret_key_ref"))
        return boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=config.region,
        )


def require_value(value: str | None, name: str) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError(f"S3-compatible storage missing required {name}")
    return str(value).strip()
