from __future__ import annotations

import pytest

from ingestion_framework.cli import main
from ingestion_framework.config.validator import SourceObjectConfig, StorageConfig
from ingestion_framework.secrets import preflight
from ingestion_framework.secrets.preflight import (
    SecretRequirement,
    check_requirements,
    collect_requirements,
)


def test_s3_storage_requires_both_key_references():
    storage = StorageConfig.model_validate(
        {
            "type": "s3_compatible",
            "bucket": "bronze",
            "endpoint_url": "http://minio:9000",
            "access_key_ref": "openbao:secret/data/ingestion-framework/minio#access_key",
            "secret_key_ref": "openbao:secret/data/ingestion-framework/minio#secret_key",
        }
    )

    requirements = collect_requirements(None, storage, None)

    assert [requirement.location for requirement in requirements] == [
        "openbao:secret/data/ingestion-framework/minio#access_key",
        "openbao:secret/data/ingestion-framework/minio#secret_key",
    ]
    assert all(not requirement.allows_env_name for requirement in requirements)


def test_local_storage_requires_no_secrets():
    storage = StorageConfig.model_validate({"type": "local", "base_path": "data/output"})

    assert collect_requirements(None, storage, None) == []


def test_api_source_uses_the_connector_default_reference():
    source = api_source(auth_type="api_key_header", connection_name="pjm")

    requirements = collect_requirements(source, None, None)

    assert len(requirements) == 1
    assert requirements[0].location == "openbao:secret/data/ingestion-framework/api/pjm#api_key"
    assert requirements[0].allows_env_name is True


def test_api_source_honors_an_explicit_reference():
    source = api_source(
        auth_type="api_key_header",
        connection_name="pjm",
        api_key_secret_ref="openbao:secret/data/ingestion-framework/api/pjm#subscription_key",
    )

    requirements = collect_requirements(source, None, None)

    assert requirements[0].location == (
        "openbao:secret/data/ingestion-framework/api/pjm#subscription_key"
    )


def test_api_source_without_auth_requires_no_secrets():
    source = api_source(auth_type="none", connection_name="open_meteo")

    assert collect_requirements(source, None, None) == []


def test_sql_server_source_requires_username_and_password():
    source = database_source(db_type="sql_server", connection_name="itron_mv90_readonly")

    requirements = collect_requirements(source, None, None)

    assert [requirement.location for requirement in requirements] == [
        "openbao:secret/data/ingestion-framework/database/itron_mv90_readonly#username",
        "openbao:secret/data/ingestion-framework/database/itron_mv90_readonly#password",
    ]


def test_sqlite_source_requires_no_secrets():
    source = database_source(db_type="sqlite", connection_name="local")

    assert collect_requirements(source, None, None) == []


@pytest.mark.parametrize(
    "audit_db, expected",
    [
        ("openbao:secret/data/ingestion-framework/audit#url", ["openbao:secret/data/ingestion-framework/audit#url"]),
        ("env:INGESTION_AUDIT_DB_URL", ["INGESTION_AUDIT_DB_URL"]),
        ("data/audit/ingestion_audit.db", []),
        ("postgresql://user:pw@postgres:5432/db", []),
    ],
)
def test_audit_db_reference_shapes(audit_db, expected):
    requirements = collect_requirements(None, None, audit_db)

    assert [requirement.location for requirement in requirements] == expected


def test_check_requirements_reports_success_and_failure(monkeypatch):
    def fake_resolve(reference):
        if "missing" in reference:
            raise KeyError("OpenBao secret field is missing: secret/data/missing#key")
        return "resolved-value"

    monkeypatch.setattr(preflight, "resolve_secret_reference", fake_resolve)

    checks = check_requirements(
        [
            SecretRequirement("present", "openbao:secret/data/present#key", False),
            SecretRequirement("absent", "openbao:secret/data/missing#key", False),
        ]
    )

    assert [check.ok for check in checks] == [True, False]
    assert checks[0].detail == "resolved"
    assert "missing" in checks[1].detail


def test_check_requirements_never_exposes_secret_values(monkeypatch):
    monkeypatch.setattr(preflight, "resolve_secret_reference", lambda reference: "hunter2")

    checks = check_requirements(
        [SecretRequirement("storage access key", "openbao:secret/data/app#key", False)]
    )

    assert checks[0].ok
    assert "hunter2" not in checks[0].detail
    assert "hunter2" not in checks[0].location
    assert "hunter2" not in checks[0].label


def test_cli_reports_resolved_references(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(preflight, "resolve_secret_reference", lambda reference: "value")
    storage_path = write_minio_storage(tmp_path)

    exit_code = main(["check-secrets", "--storage", str(storage_path)])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "2 of 2 secret references resolved." in output
    assert "value" not in output


def test_cli_exits_nonzero_when_a_reference_fails(tmp_path, monkeypatch, capsys):
    def fail(reference):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(preflight, "resolve_secret_reference", fail)
    storage_path = write_minio_storage(tmp_path)

    exit_code = main(["check-secrets", "--storage", str(storage_path)])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "FAIL" in output
    assert "connection refused" in output


def test_cli_requires_at_least_one_target():
    with pytest.raises(SystemExit):
        main(["check-secrets"])


def write_minio_storage(tmp_path):
    path = tmp_path / "storage_minio.yaml"
    path.write_text(
        """
storages:
  minio_bronze:
    type: s3_compatible
    bucket: bronze
    endpoint_url: http://minio:9000
    access_key_ref: openbao:secret/data/ingestion-framework/minio#access_key
    secret_key_ref: openbao:secret/data/ingestion-framework/minio#secret_key
"""
    )
    return path


def api_source(**extraction_overrides) -> SourceObjectConfig:
    extraction = {
        "base_url": "https://api.example.test",
        "endpoint": "/data",
        "method": "GET",
    }
    extraction.update(extraction_overrides)
    return SourceObjectConfig.model_validate(
        {
            "object_id": "example_api",
            "source_system": "example",
            "source_type": "api",
            "object_name": "example",
            "load_strategy": "full",
            "extraction": extraction,
            "schema": {"columns": {"value": {"type": "string", "nullable": True}}},
            "target": target(),
            "security": security(),
        }
    )


def database_source(**extraction_overrides) -> SourceObjectConfig:
    extraction = {"table_name": "customers", "schema_name": "dbo"}
    extraction.update(extraction_overrides)
    return SourceObjectConfig.model_validate(
        {
            "object_id": "example_db",
            "source_system": "example",
            "source_type": "database",
            "object_name": "customers",
            "load_strategy": "full",
            "extraction": extraction,
            "schema": {"columns": {"id": {"type": "integer", "nullable": False}}},
            "target": target(),
            "security": security(),
        }
    )


def target() -> dict:
    return {
        "storage_name": "local_bronze",
        "zone": "bronze",
        "format": "parquet",
        "write_mode": "append",
        "compression": "snappy",
        "partition_by": ["ingest_year"],
    }


def security() -> dict:
    return {
        "classification": "internal",
        "contains_bcsi": False,
        "contains_pii": False,
        "encryption_required": False,
        "masking_required": False,
        "raw_payload_retention_days": 30,
        "access_group": "data_platform_users",
    }
