from __future__ import annotations

from pathlib import Path

from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.writers.storage.adls_gen2 import AdlsGen2StorageWriter
from ingestion_framework.writers.storage.base import BaseStorageWriter
from ingestion_framework.writers.storage.local import LocalStorageWriter
from ingestion_framework.writers.storage.s3_compatible import S3CompatibleStorageWriter

ADLS_TYPES = {"adls_gen2", "adls"}
S3_TYPES = {"s3_compatible", "s3"}


def build_storage_writer(
    config: StorageConfig,
    base_dir: str | Path | None = None,
) -> BaseStorageWriter:
    if config.type == "local":
        return LocalStorageWriter(config, base_dir)
    if config.type in S3_TYPES:
        return S3CompatibleStorageWriter(config)
    if config.type in ADLS_TYPES:
        return AdlsGen2StorageWriter(config)
    raise ValueError(f"Unsupported storage type: {config.type}")
