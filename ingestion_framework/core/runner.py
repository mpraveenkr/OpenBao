from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ingestion_framework.audit.factory import create_persistence_stores
from ingestion_framework.config.loader import ConfigLoader
from ingestion_framework.config.validator import SecurityPolicyValidator
from ingestion_framework.processors.base import ProcessorContext
from ingestion_framework.processors.registry import ProcessorRegistry


class IngestionRunner:
    def __init__(
        self,
        source_config_path: str | Path,
        storage_config_path: str | Path,
        audit_db_path: str | Path,
        base_dir: str | Path | None = None,
    ) -> None:
        self.source_config_path = Path(source_config_path)
        self.storage_config_path = Path(storage_config_path)
        self.audit_db_path = audit_db_path
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()

    def run(self) -> dict[str, object]:
        loader = ConfigLoader()
        source = loader.load_source(self._resolve_path(self.source_config_path))
        if not source.enabled:
            return {
                "run_id": None,
                "status": "SKIPPED",
                "source_type": source.source_type,
                "object_id": source.object_id,
                "rows_extracted": 0,
                "rows_written": 0,
                "target_path": None,
                "manifest_path": None,
            }
        storage_registry = loader.load_storage(self._resolve_path(self.storage_config_path))
        if source.target.storage_name not in storage_registry.storages:
            raise ValueError(
                f"Target storage is not defined in storage config: {source.target.storage_name}"
            )
        storage = storage_registry.storages[source.target.storage_name]
        SecurityPolicyValidator.validate(source, storage)

        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid4().hex[:8]
        persistence = create_persistence_stores(
            self.audit_db_path,
            base_dir=self.base_dir,
        )
        audit_logger = persistence.audit_logger
        watermark_store = persistence.watermark_store
        audit_logger.start_run(run_id, source)

        try:
            processor = ProcessorRegistry().get(source)
            result = processor.run(
                ProcessorContext(
                    source=source,
                    storage=storage,
                    run_id=run_id,
                    base_dir=self.base_dir,
                    watermark_store=watermark_store,
                )
            )
            audit_logger.complete_run(
                run_id,
                result.rows_extracted,
                result.rows_written,
                result.target_path,
            )
            if result.watermark_value is not None:
                watermark_store.commit_watermark(
                    source.object_id, result.watermark_value, run_id
                )
            return {
                "run_id": run_id,
                "status": "SUCCESS",
                "source_type": source.source_type,
                "object_id": source.object_id,
                "rows_extracted": result.rows_extracted,
                "rows_written": result.rows_written,
                "target_path": result.target_path,
                "manifest_path": result.manifest_path,
            }
        except Exception as exc:
            audit_logger.fail_run(run_id, str(exc))
            raise

    def _resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.base_dir / candidate
