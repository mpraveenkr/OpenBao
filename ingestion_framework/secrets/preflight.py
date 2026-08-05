"""Resolve every secret a source object needs, without revealing any values.

This backs `ingest-object check-secrets`, which lets an operator prove the
OpenBao wiring on a host before trusting a scheduled DAG run.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ingestion_framework.secrets.resolver import resolve_env_or_secret, resolve_secret_reference


@dataclass(frozen=True)
class SecretRequirement:
    """One secret a config depends on, described without its value."""

    label: str
    location: str
    # Storage refs must be inline references; API and database credentials may
    # also name an environment variable, matching how each connector resolves.
    allows_env_name: bool


@dataclass(frozen=True)
class SecretCheck:
    label: str
    location: str
    ok: bool
    detail: str


def collect_requirements(
    source: Any | None,
    storage: Any | None,
    audit_db: str | None,
) -> list[SecretRequirement]:
    requirements: list[SecretRequirement] = []
    if storage is not None:
        requirements.extend(_storage_requirements(storage))
    if source is not None:
        requirements.extend(_source_requirements(source))
    if audit_db:
        requirements.extend(_audit_requirements(audit_db))
    return requirements


def check_requirements(requirements: list[SecretRequirement]) -> list[SecretCheck]:
    checks: list[SecretCheck] = []
    for requirement in requirements:
        try:
            if requirement.allows_env_name:
                resolve_env_or_secret(requirement.location, label=requirement.label)
            else:
                resolve_secret_reference(requirement.location)
        except Exception as exc:
            checks.append(
                SecretCheck(
                    label=requirement.label,
                    location=requirement.location,
                    ok=False,
                    # Only the exception type and message are surfaced. Resolvers
                    # never put secret values in their messages.
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
            continue
        checks.append(
            SecretCheck(
                label=requirement.label,
                location=requirement.location,
                ok=True,
                detail="resolved",
            )
        )
    return checks


def _storage_requirements(storage: Any) -> list[SecretRequirement]:
    if storage.type not in {"s3", "s3_compatible"}:
        return []
    return [
        SecretRequirement("storage access key", str(storage.access_key_ref), False),
        SecretRequirement("storage secret key", str(storage.secret_key_ref), False),
    ]


def _source_requirements(source: Any) -> list[SecretRequirement]:
    source_type = str(getattr(source, "source_type", "") or "")
    if source_type == "api":
        return _api_requirements(source)
    if source_type == "database":
        return _database_requirements(source)
    return []


def _api_requirements(source: Any) -> list[SecretRequirement]:
    from ingestion_framework.connectors.api import api_key_secret_location

    if str(source.extraction.auth_type or "none") != "api_key_header":
        return []
    return [SecretRequirement("API key", api_key_secret_location(source), True)]


def _database_requirements(source: Any) -> list[SecretRequirement]:
    from ingestion_framework.connectors.api import get_extra
    from ingestion_framework.connectors.database import sql_server_secret_ref

    extraction = source.extraction
    db_type = str(extraction.db_type or "").lower().replace(" ", "_")
    if db_type not in {"sql_server", "mssql"}:
        return []

    connection_name = str(extraction.connection_name or "").strip()
    username = get_extra(extraction, "username_secret_ref") or sql_server_secret_ref(
        connection_name, "username"
    )
    password = get_extra(extraction, "password_secret_ref") or sql_server_secret_ref(
        connection_name, "password"
    )
    return [
        SecretRequirement(f"{connection_name} SQL Server username", str(username), True),
        SecretRequirement(f"{connection_name} SQL Server password", str(password), True),
    ]


def _audit_requirements(audit_db: str) -> list[SecretRequirement]:
    from ingestion_framework.secrets.resolver import is_secret_reference

    value = audit_db.strip()
    if is_secret_reference(value):
        return [SecretRequirement("audit database URL", value, False)]
    if value.startswith("env:"):
        env_name = value.removeprefix("env:").strip()
        if not env_name:
            raise ValueError("Audit database environment reference cannot be empty")
        return [SecretRequirement("audit database URL", env_name, True)]
    # A plain SQLite path or Postgres URL needs no secret resolution.
    return []
