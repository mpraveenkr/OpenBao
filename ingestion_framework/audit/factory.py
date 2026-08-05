from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingestion_framework.audit.audit_logger import (
    AuditLogger,
    PostgresAuditLogger,
    SQLiteAuditLogger,
)
from ingestion_framework.audit.watermark_store import (
    PostgresWatermarkStore,
    SQLiteWatermarkStore,
    WatermarkStore,
)
from ingestion_framework.secrets import resolve_env_or_secret, resolve_value


@dataclass(frozen=True)
class PersistenceStores:
    audit_logger: AuditLogger
    watermark_store: WatermarkStore


def create_persistence_stores(
    audit_db: str | Path,
    *,
    base_dir: str | Path | None = None,
) -> PersistenceStores:
    """Create audit and watermark stores from a SQLite path or Postgres URL."""
    value = resolve_audit_db_reference(str(audit_db)).strip()
    if _is_postgres_url(value):
        database_url = _normalize_postgres_url(value)
        return PersistenceStores(
            audit_logger=PostgresAuditLogger(database_url),
            watermark_store=PostgresWatermarkStore(database_url),
        )

    sqlite_path = _resolve_sqlite_path(value, base_dir=base_dir)
    return PersistenceStores(
        audit_logger=SQLiteAuditLogger(sqlite_path),
        watermark_store=SQLiteWatermarkStore(sqlite_path),
    )


def resolve_audit_db_reference(value: str) -> str:
    """Resolve an --audit-db value that may be an OpenBao reference or env:NAME."""
    resolved = resolve_value(value)
    if resolved != value:
        return str(resolved)
    if not value.startswith("env:"):
        return value
    env_name = value.removeprefix("env:").strip()
    if not env_name:
        raise ValueError("Audit database environment reference cannot be empty")
    try:
        return resolve_env_or_secret(env_name, label="audit database URL")
    except RuntimeError as exc:
        raise ValueError(f"Audit database environment variable is not set: {env_name}") from exc


def _is_postgres_url(value: str) -> bool:
    return value.startswith(("postgresql://", "postgresql+", "postgres://"))


def _normalize_postgres_url(value: str) -> str:
    if value.startswith("postgres://"):
        return "postgresql://" + value.removeprefix("postgres://")
    return value


def _resolve_sqlite_path(value: str, *, base_dir: str | Path | None) -> Path:
    if value.startswith("sqlite:///"):
        value = value.removeprefix("sqlite:///")
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (Path(base_dir) if base_dir else Path.cwd()) / candidate
