from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ingestion_framework.config.validator import SourceObjectConfig, StorageConfig


class ManifestWriter:
    def build(
        self,
        source: SourceObjectConfig,
        storage: StorageConfig,
        run_id: str,
        rows_extracted: int,
        rows_written: int,
        target_files: list[str],
    ) -> dict[str, object]:
        return {
            "run_id": run_id,
            "object_id": source.object_id,
            "source_system": source.source_system,
            "source_type": source.source_type,
            "object_name": source.object_name,
            "load_strategy": source.load_strategy,
            "rows_extracted": rows_extracted,
            "rows_written": rows_written,
            "target_files": target_files,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "classification": source.security.classification,
            "contains_bcsi": source.security.contains_bcsi,
            "contains_pii": source.security.contains_pii,
            "encryption_required": source.security.encryption_required,
            "masking_required": source.security.masking_required,
            "masking_policy_applied": self._masking_policy_applied(source),
            "storage_encryption_mode": storage.encryption.mode,
        }

    def write(self, manifest: dict[str, object], path: str | Path) -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return output_path

    @staticmethod
    def _masking_policy_applied(source: SourceObjectConfig) -> bool:
        return any(
            column.mask_policy and column.mask_policy.lower() != "none"
            for column in source.schema.columns.values()
        )
