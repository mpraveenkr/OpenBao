from __future__ import annotations

import shutil
from pathlib import Path

from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.writers.storage.base import BaseStorageWriter


class LocalStorageWriter(BaseStorageWriter):
    def __init__(self, config: StorageConfig, base_dir: str | Path | None = None) -> None:
        self.config = config
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.base_path = self._resolve_path(config.base_path)

    def write_file(self, source_file: str | Path, target_key: str) -> Path:
        target_path = self.base_path / target_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target_path)
        return target_path

    def write_bytes(self, content: bytes, target_key: str) -> Path:
        target_path = self.base_path / target_key
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
        return target_path

    def _resolve_path(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.base_dir / candidate
