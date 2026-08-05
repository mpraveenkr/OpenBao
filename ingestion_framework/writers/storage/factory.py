from __future__ import annotations

from pathlib import Path

from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.writers.storage.base import BaseStorageWriter
from ingestion_framework.writers.storage.local import LocalStorageWriter
from ingestion_framework.writers.storage.s3_compatible import S3CompatibleStorageWriter


def build_storage_writer(
    config: StorageConfig,
    base_dir: str | Path | None = None,
) -> BaseStorageWriter:
    if config.type == "local":
        return LocalStorageWriter(config, base_dir)
    if config.type in {"s3_compatible", "s3"}:
        return S3CompatibleStorageWriter(config)
    raise ValueError(f"Unsupported storage type: {config.type}")
