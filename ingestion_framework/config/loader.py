from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ingestion_framework.config.validator import SourceObjectConfig, StorageRegistryConfig


class ConfigLoader:
    """Loads YAML metadata into validated config models."""

    def load_source(self, path: str | Path) -> SourceObjectConfig:
        data = self._load_yaml(path)
        return SourceObjectConfig.model_validate(data)

    def load_storage(self, path: str | Path) -> StorageRegistryConfig:
        data = self._load_yaml(path)
        return StorageRegistryConfig.model_validate(data)

    @staticmethod
    def _load_yaml(path: str | Path) -> dict[str, Any]:
        config_path = Path(path)
        with config_path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        if not isinstance(data, dict):
            raise ValueError(f"Config file must contain a YAML mapping: {config_path}")
        return data
