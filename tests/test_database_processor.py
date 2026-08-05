from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq
import pytest
import yaml

from ingestion_framework.core.runner import IngestionRunner
from ingestion_framework.connectors.database import (
    build_sql_and_params,
    map_postgres_type,
    map_sql_server_type,
    map_sqlite_type,
)
from ingestion_framework.audit.watermark_store import SQLiteWatermarkStore
from ingestion_framework.config.validator import SourceObjectConfig


def test_database_processor_full_infer_loads_all_columns(tmp_path):
    db_path = make_sqlite_source(tmp_path)
    source_path = write_source_config(
        tmp_path,
        {
            "object_id": "sqlite_customers_full",
            "source_system": "sqlite_test",
            "source_type": "database",
            "object_name": "customers",
            "enabled": True,
            "load_strategy": "full",
            "extraction": {
                "db_type": "sqlite",
                "connection_name": "sqlite_test",
                "database_name": str(db_path),
                "table_name": "customers",
            },
            "schema_policy": {
                "mode": "infer",
                "column_discovery": "source_metadata",
                "type_discovery": "source_metadata",
                "include_unmodeled_columns": True,
                "infer_types": True,
            },
            "schema": {"columns": {}},
            "target": target_config(),
            "audit": {"dq_checks": ["row_count_gt_zero"], "primary_key": []},
            "security": security(),
        },
    )

    result = run_ingestion(tmp_path, source_path)

    frame = pd.read_parquet(result["target_path"])
    assert result["rows_written"] == 2
    assert {"customer_id", "customer_name", "last_updated", "amount", "active_flag"}.issubset(frame.columns)
    assert str(frame["customer_id"].dtype) == "string"
    assert str(frame["amount"].dtype) == "float64"
    assert str(frame["active_flag"].dtype) == "Int64"
    manifest = json.loads(Path(result["manifest_path"]).read_text())
    assert manifest["schema_mode"] == "infer"
    assert manifest["runtime_schema_columns"] == 5


def test_database_processor_incremental_hybrid_commits_watermark(tmp_path):
    db_path = make_sqlite_source(tmp_path)
    source_path = write_source_config(
        tmp_path,
        {
            "object_id": "sqlite_customers_incremental",
            "source_system": "sqlite_test",
            "source_type": "database",
            "object_name": "customers",
            "enabled": True,
            "load_strategy": "incremental",
            "extraction": {
                "db_type": "sqlite",
                "connection_name": "sqlite_test",
                "database_name": str(db_path),
                "table_name": "customers",
                "query": "SELECT * FROM customers WHERE last_updated > :last_watermark",
                "incremental_column": "last_updated",
                "watermark_type": "timestamp",
                "watermark": {
                    "column": "last_updated",
                    "operator": ">",
                    "initial_value": "2026-01-01T00:00:00Z",
                    "value_type": "timestamp",
                    "timezone": "UTC",
                    "commit_rule": "max_extracted_value_after_successful_write",
                    "late_arriving_overlap": "0 minutes",
                },
            },
            "schema_policy": {
                "mode": "hybrid",
                "column_discovery": "source_metadata",
                "type_discovery": "source_metadata",
                "include_unmodeled_columns": True,
                "infer_types": True,
            },
            "schema": {
                "columns": {
                    "customer_id": {
                        "type": "string",
                        "nullable": False,
                        "mask_policy": "none",
                        "source_column_name": "customer_id",
                    },
                    "last_updated": {
                        "type": "timestamp",
                        "nullable": False,
                        "mask_policy": "none",
                        "source_column_name": "last_updated",
                    },
                }
            },
            "target": target_config(),
            "audit": {"dq_checks": ["row_count_gt_zero"], "primary_key": ["customer_id"]},
            "security": security(),
        },
    )

    result = run_ingestion(tmp_path, source_path)

    assert result["rows_written"] == 2
    with sqlite3.connect(tmp_path / "audit" / "ingestion_audit.db") as conn:
        watermark = conn.execute(
            "SELECT watermark_value FROM ingestion_watermark WHERE object_id = ?",
            ("sqlite_customers_incremental",),
        ).fetchone()
    assert watermark is not None
    assert watermark[0].startswith("2026-01-03T00:00:00")


def test_database_processor_streams_fetch_size_chunks_to_parquet_row_groups(tmp_path):
    db_path = make_sqlite_source(tmp_path)
    source_path = write_source_config(
        tmp_path,
        {
            "object_id": "sqlite_customers_streaming",
            "source_system": "sqlite_test",
            "source_type": "database",
            "object_name": "customers",
            "enabled": True,
            "load_strategy": "full",
            "extraction": {
                "db_type": "sqlite",
                "connection_name": "sqlite_test",
                "database_name": str(db_path),
                "table_name": "customers",
                "fetch_size": 1,
            },
            "schema_policy": {
                "mode": "infer",
                "column_discovery": "source_metadata",
                "type_discovery": "source_metadata",
                "include_unmodeled_columns": True,
                "infer_types": True,
            },
            "schema": {"columns": {}},
            "target": target_config(),
            "audit": {"dq_checks": ["row_count_gt_zero"], "primary_key": []},
            "security": security(),
        },
    )

    result = run_ingestion(tmp_path, source_path)

    parquet_file = pq.ParquetFile(result["target_path"])
    manifest = json.loads(Path(result["manifest_path"]).read_text())

    assert result["rows_written"] == 2
    assert parquet_file.metadata.num_row_groups == 2
    assert manifest["write_mode"] == "streaming_chunks"


def test_database_processor_incremental_requires_watermark(tmp_path):
    db_path = make_sqlite_source(tmp_path)
    source_path = write_source_config(
        tmp_path,
        {
            "object_id": "sqlite_customers_bad_incremental",
            "source_system": "sqlite_test",
            "source_type": "database",
            "object_name": "customers",
            "enabled": True,
            "load_strategy": "incremental",
            "extraction": {
                "db_type": "sqlite",
                "connection_name": "sqlite_test",
                "database_name": str(db_path),
                "table_name": "customers",
            },
            "schema_policy": {"mode": "infer", "include_unmodeled_columns": True},
            "schema": {"columns": {}},
            "target": target_config(),
            "audit": {"dq_checks": ["row_count_gt_zero"], "primary_key": []},
            "security": security(),
        },
    )

    try:
        run_ingestion(tmp_path, source_path)
    except ValueError as exc:
        assert "incremental database load requires a watermark column" in str(exc)
    else:
        raise AssertionError("Expected incremental database validation to fail")


def test_generated_incremental_sql_quotes_watermark_identifier():
    source = SourceObjectConfig.model_validate(
        {
            "object_id": "safe_incremental",
            "source_system": "sqlite_test",
            "source_type": "database",
            "object_name": "customers",
            "enabled": True,
            "load_strategy": "incremental",
            "extraction": {
                "db_type": "sqlite",
                "connection_name": "sqlite_test",
                "database_name": "unused.db",
                "table_name": "customers",
                "incremental_column": "last_updated; DROP TABLE customers",
            },
            "schema_policy": {"mode": "infer"},
            "schema": {"columns": {}},
            "target": target_config(),
            "security": security(),
        }
    )

    with pytest.raises(ValueError, match="Unsafe database identifier"):
        build_sql_and_params(source)


def test_watermark_store_keeps_one_current_row_per_object(tmp_path):
    store = SQLiteWatermarkStore(tmp_path / "audit.db")

    store.commit_watermark("object_a", "1", "run-1")
    store.commit_watermark("object_a", "2", "run-2")

    assert store.get_last_watermark("object_a") == "2"
    with sqlite3.connect(tmp_path / "audit.db") as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM ingestion_watermark WHERE object_id = ?",
            ("object_a",),
        ).fetchone()[0]
    assert count == 1


def test_database_metadata_type_mapping_is_database_specific():
    assert map_sql_server_type("NVARCHAR(100)") == "string"
    assert map_sql_server_type("DATETIME2") == "timestamp"
    assert map_sql_server_type("BIT") == "boolean"
    assert map_sql_server_type("DECIMAL(18,2)") == "decimal"
    assert map_sql_server_type("BIGINT") == "bigint"

    assert map_postgres_type("TIMESTAMP WITH TIME ZONE") == "timestamp"
    assert map_postgres_type("NUMERIC") == "decimal"
    assert map_postgres_type("BOOLEAN") == "boolean"

    assert map_sqlite_type("REAL") == "float"
    assert map_sqlite_type("INTEGER") == "integer"


def make_sqlite_source(tmp_path: Path) -> Path:
    db_path = tmp_path / "source.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE customers (
                customer_id TEXT,
                customer_name TEXT,
                last_updated TEXT,
                amount REAL,
                active_flag INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
            [
                ("1001", "Acme Power", "2026-01-02T00:00:00Z", 10.5, 1),
                ("1002", "Blue River", "2026-01-03T00:00:00Z", 20.75, 0),
            ],
        )
    return db_path


def run_ingestion(tmp_path: Path, source_path: Path):
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
    return IngestionRunner(
        source_config_path=source_path,
        storage_config_path=storage_path,
        audit_db_path=tmp_path / "audit" / "ingestion_audit.db",
        base_dir=tmp_path,
    ).run()


def write_source_config(tmp_path: Path, config: dict) -> Path:
    source_path = tmp_path / f"{config['object_id']}.yaml"
    source_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return source_path


def target_config():
    return {
        "storage_name": "local_bronze",
        "zone": "bronze",
        "format": "parquet",
        "write_mode": "append",
        "compression": "snappy",
        "partition_by": ["ingest_year", "ingest_month", "ingest_day"],
    }


def security():
    return {
        "classification": "internal",
        "contains_bcsi": False,
        "contains_pii": False,
        "encryption_required": False,
        "masking_required": False,
        "raw_payload_retention_days": 30,
        "access_group": "data_platform_users",
    }
