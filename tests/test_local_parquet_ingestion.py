from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
import yaml

import ingestion_framework.core.runner as runner_module
from ingestion_framework.core.runner import IngestionRunner


def test_full_local_ingestion_creates_parquet_manifest_and_success_audit(tmp_path):
    project_root = Path.cwd()
    storage_config = {
        "storages": {
            "local_bronze": {
                "type": "local",
                "base_path": str(tmp_path / "output"),
                "encryption": {"supported": False, "mode": "none"},
            }
        }
    }
    storage_path = tmp_path / "storage.yaml"
    storage_path.write_text(yaml.safe_dump(storage_config), encoding="utf-8")
    audit_db = tmp_path / "audit" / "ingestion_audit.db"

    result = IngestionRunner(
        source_config_path=project_root / "configs/sources/sample_csv_customers.yaml",
        storage_config_path=storage_path,
        audit_db_path=audit_db,
        base_dir=project_root,
    ).run()

    parquet_path = Path(result["target_path"])
    manifest_path = Path(result["manifest_path"])
    assert parquet_path.exists()
    assert manifest_path.exists()
    assert manifest_path.name == "_manifest.json"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["rows_written"] == 2
    assert manifest["classification"] == "internal"
    assert manifest["storage_encryption_mode"] == "none"

    with sqlite3.connect(audit_db) as conn:
        row = conn.execute(
            "SELECT status, rows_extracted, rows_written FROM ingestion_pipeline_run"
        ).fetchone()

    assert row == ("SUCCESS", 2, 2)


def test_disabled_source_is_skipped_without_audit_or_write(tmp_path):
    source_config = yaml.safe_load(
        Path("configs/sources/sample_csv_customers.yaml").read_text(encoding="utf-8")
    )
    source_config["enabled"] = False
    source_path = tmp_path / "disabled.yaml"
    source_path.write_text(yaml.safe_dump(source_config), encoding="utf-8")
    storage_path = write_local_storage(tmp_path)

    result = IngestionRunner(
        source_config_path=source_path,
        storage_config_path=storage_path,
        audit_db_path=tmp_path / "audit" / "ingestion_audit.db",
        base_dir=Path.cwd(),
    ).run()

    assert result["status"] == "SKIPPED"
    assert result["run_id"] is None
    assert not (tmp_path / "audit" / "ingestion_audit.db").exists()


def test_failed_processor_does_not_commit_watermark(tmp_path, monkeypatch):
    source_config = yaml.safe_load(
        Path("configs/sources/sample_csv_customers.yaml").read_text(encoding="utf-8")
    )
    source_path = tmp_path / "source.yaml"
    source_path.write_text(yaml.safe_dump(source_config), encoding="utf-8")
    storage_path = write_local_storage(tmp_path)

    class FailingRegistry:
        def get(self, source):
            return FailingProcessor()

    class FailingProcessor:
        def run(self, context):
            raise RuntimeError("write failed with PWD=super-secret")

    monkeypatch.setattr(runner_module, "ProcessorRegistry", FailingRegistry)

    with pytest.raises(RuntimeError, match="write failed"):
        IngestionRunner(
            source_config_path=source_path,
            storage_config_path=storage_path,
            audit_db_path=tmp_path / "audit" / "ingestion_audit.db",
            base_dir=Path.cwd(),
        ).run()

    with sqlite3.connect(tmp_path / "audit" / "ingestion_audit.db") as conn:
        watermark_count = conn.execute(
            "SELECT COUNT(*) FROM ingestion_watermark"
        ).fetchone()[0]
        error_message = conn.execute(
            "SELECT error_message FROM ingestion_pipeline_run"
        ).fetchone()[0]

    assert watermark_count == 0
    assert "super-secret" not in error_message
    assert "***REDACTED***" in error_message


def write_local_storage(tmp_path: Path) -> Path:
    storage_path = tmp_path / "storage.yaml"
    storage_path.write_text(
        yaml.safe_dump(
            {
                "storages": {
                    "local_bronze": {
                        "type": "local",
                        "base_path": str(tmp_path / "output"),
                        "encryption": {"supported": False, "mode": "none"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return storage_path
