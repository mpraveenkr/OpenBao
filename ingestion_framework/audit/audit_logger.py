from __future__ import annotations

import sqlite3
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from ingestion_framework.config.validator import SourceObjectConfig


SENSITIVE_ERROR_PATTERNS = [
    re.compile(
        r"((?:PWD|password|passwd|secret|token)\s*=\s*)[^\s;\"']+",
        flags=re.IGNORECASE,
    ),
    re.compile(
        r"((?:postgresql|postgres|mssql(?:\\+pyodbc)?)://[^:\s/]+:)([^@\s]+)(@)",
        flags=re.IGNORECASE,
    ),
]


def sanitize_error_message(error_message: str) -> str:
    redacted = str(error_message)
    for pattern in SENSITIVE_ERROR_PATTERNS:
        if pattern.groups >= 3:
            redacted = pattern.sub(r"\1***REDACTED***\3", redacted)
        else:
            redacted = pattern.sub(r"\1***REDACTED***", redacted)
    return redacted[:2000]


class AuditLogger(Protocol):
    def start_run(self, run_id: str, source: SourceObjectConfig) -> None:
        """Record that an ingestion run has started."""

    def complete_run(
        self,
        run_id: str,
        rows_extracted: int,
        rows_written: int,
        target_path: str,
    ) -> None:
        """Record that an ingestion run completed successfully."""

    def fail_run(self, run_id: str, error_message: str) -> None:
        """Record that an ingestion run failed."""


class SQLiteAuditLogger:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def start_run(self, run_id: str, source: SourceObjectConfig) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_pipeline_run (
                    run_id, object_id, source_system, source_type, object_name,
                    status, start_time_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    source.object_id,
                    source.source_system,
                    source.source_type,
                    source.object_name,
                    "RUNNING",
                    self._now(),
                ),
            )

    def complete_run(
        self,
        run_id: str,
        rows_extracted: int,
        rows_written: int,
        target_path: str,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_pipeline_run
                SET status = ?, end_time_utc = ?, rows_extracted = ?,
                    rows_written = ?, target_path = ?, error_message = NULL
                WHERE run_id = ?
                """,
                ("SUCCESS", self._now(), rows_extracted, rows_written, target_path, run_id),
            )

    def fail_run(self, run_id: str, error_message: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_pipeline_run
                SET status = ?, end_time_utc = ?, error_message = ?
                WHERE run_id = ?
                """,
                ("FAILED", self._now(), self._sanitize_error(error_message), run_id),
            )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_pipeline_run (
                    run_id TEXT PRIMARY KEY,
                    object_id TEXT,
                    source_system TEXT,
                    source_type TEXT,
                    object_name TEXT,
                    status TEXT,
                    start_time_utc TEXT,
                    end_time_utc TEXT,
                    rows_extracted INTEGER,
                    rows_written INTEGER,
                    target_path TEXT,
                    error_message TEXT
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _sanitize_error(error_message: str) -> str:
        return sanitize_error_message(error_message)


class PostgresAuditLogger:
    def __init__(self, database_url: str, engine: Engine | None = None) -> None:
        self.database_url = database_url
        self.engine = engine if engine is not None else create_engine(database_url, future=True)
        self._init_db()

    def start_run(self, run_id: str, source: SourceObjectConfig) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO ingestion_pipeline_run (
                        run_id, object_id, source_system, source_type, object_name,
                        status, start_time_utc
                    ) VALUES (
                        :run_id, :object_id, :source_system, :source_type, :object_name,
                        :status, :start_time_utc
                    )
                    """
                ),
                {
                    "run_id": run_id,
                    "object_id": source.object_id,
                    "source_system": source.source_system,
                    "source_type": source.source_type,
                    "object_name": source.object_name,
                    "status": "RUNNING",
                    "start_time_utc": self._now(),
                },
            )

    def complete_run(
        self,
        run_id: str,
        rows_extracted: int,
        rows_written: int,
        target_path: str,
    ) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ingestion_pipeline_run
                    SET status = :status,
                        end_time_utc = :end_time_utc,
                        rows_extracted = :rows_extracted,
                        rows_written = :rows_written,
                        target_path = :target_path,
                        error_message = NULL
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "status": "SUCCESS",
                    "end_time_utc": self._now(),
                    "rows_extracted": rows_extracted,
                    "rows_written": rows_written,
                    "target_path": target_path,
                    "run_id": run_id,
                },
            )

    def fail_run(self, run_id: str, error_message: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    UPDATE ingestion_pipeline_run
                    SET status = :status,
                        end_time_utc = :end_time_utc,
                        error_message = :error_message
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "status": "FAILED",
                    "end_time_utc": self._now(),
                    "error_message": self._sanitize_error(error_message),
                    "run_id": run_id,
                },
            )

    def _init_db(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_pipeline_run (
                        run_id TEXT PRIMARY KEY,
                        object_id TEXT NOT NULL,
                        source_system TEXT,
                        source_type TEXT,
                        object_name TEXT,
                        status TEXT NOT NULL,
                        start_time_utc TIMESTAMPTZ,
                        end_time_utc TIMESTAMPTZ,
                        rows_extracted BIGINT,
                        rows_written BIGINT,
                        target_path TEXT,
                        error_message TEXT
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ingestion_pipeline_run_object_start
                    ON ingestion_pipeline_run (object_id, start_time_utc DESC)
                    """
                )
            )

    @staticmethod
    def _now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _sanitize_error(error_message: str) -> str:
        return sanitize_error_message(error_message)


def create_postgres_audit_logger(database_url: str, engine: Engine | None = None) -> PostgresAuditLogger:
    return PostgresAuditLogger(database_url, engine=engine)
