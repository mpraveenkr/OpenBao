from __future__ import annotations

from pathlib import Path

import pytest

from ingestion_framework.audit import factory
from ingestion_framework.audit.audit_logger import SQLiteAuditLogger, sanitize_error_message
from ingestion_framework.audit.watermark_store import SQLiteWatermarkStore


def test_factory_uses_sqlite_for_filesystem_path(tmp_path):
    stores = factory.create_persistence_stores(
        "audit/ingestion_audit.db",
        base_dir=tmp_path,
    )

    assert isinstance(stores.audit_logger, SQLiteAuditLogger)
    assert isinstance(stores.watermark_store, SQLiteWatermarkStore)
    assert stores.audit_logger.db_path == tmp_path / "audit" / "ingestion_audit.db"
    assert stores.watermark_store.db_path == tmp_path / "audit" / "ingestion_audit.db"


def test_factory_resolves_postgres_url_from_environment(monkeypatch):
    created: list[str] = []

    class FakeAuditLogger:
        def __init__(self, database_url: str) -> None:
            created.append(f"audit:{database_url}")

    class FakeWatermarkStore:
        def __init__(self, database_url: str) -> None:
            created.append(f"watermark:{database_url}")

    monkeypatch.setenv(
        "INGESTION_AUDIT_DB_URL",
        "postgres://ingestion_app:secret@postgres:5432/ingestion_metadata",
    )
    monkeypatch.setattr(factory, "PostgresAuditLogger", FakeAuditLogger)
    monkeypatch.setattr(factory, "PostgresWatermarkStore", FakeWatermarkStore)

    factory.create_persistence_stores("env:INGESTION_AUDIT_DB_URL")

    assert created == [
        "audit:postgresql://ingestion_app:secret@postgres:5432/ingestion_metadata",
        "watermark:postgresql://ingestion_app:secret@postgres:5432/ingestion_metadata",
    ]


def test_factory_resolves_postgres_url_from_openbao_reference(monkeypatch):
    created: list[str] = []

    class FakeAuditLogger:
        def __init__(self, database_url: str) -> None:
            created.append(f"audit:{database_url}")

    class FakeWatermarkStore:
        def __init__(self, database_url: str) -> None:
            created.append(f"watermark:{database_url}")

    monkeypatch.setenv("OPENBAO_ADDR", "http://openbao:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "token")
    monkeypatch.setattr(factory, "PostgresAuditLogger", FakeAuditLogger)
    monkeypatch.setattr(factory, "PostgresWatermarkStore", FakeWatermarkStore)
    monkeypatch.setattr(
        "ingestion_framework.secrets.openbao.requests.Session",
        lambda: FakeSession(
            {
                "data": {
                    "data": {
                        "url": "postgres://ingestion_app:secret@postgres:5432/ingestion_metadata"
                    }
                }
            }
        ),
    )

    factory.create_persistence_stores(
        "openbao:secret/data/ingestion-framework/audit#url"
    )

    assert created == [
        "audit:postgresql://ingestion_app:secret@postgres:5432/ingestion_metadata",
        "watermark:postgresql://ingestion_app:secret@postgres:5432/ingestion_metadata",
    ]


def test_factory_rejects_missing_environment_reference(monkeypatch):
    monkeypatch.delenv("INGESTION_AUDIT_DB_URL", raising=False)

    with pytest.raises(ValueError, match="environment variable is not set"):
        factory.create_persistence_stores("env:INGESTION_AUDIT_DB_URL")


def test_factory_accepts_sqlite_url(tmp_path):
    stores = factory.create_persistence_stores(
        f"sqlite:///{tmp_path / 'audit.db'}",
        base_dir=Path("/unused"),
    )

    assert isinstance(stores.audit_logger, SQLiteAuditLogger)
    assert stores.audit_logger.db_path == tmp_path / "audit.db"


def test_error_sanitizer_redacts_common_secret_shapes():
    sanitized = sanitize_error_message(
        "Login failed for postgresql://ingestion_app:plain-password@postgres/db; "
        "PWD=another-password; token=abc123"
    )

    assert "plain-password" not in sanitized
    assert "another-password" not in sanitized
    assert "abc123" not in sanitized
    assert "***REDACTED***" in sanitized


class FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def get(self, url: str, headers: dict[str, str], timeout: int):
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload
