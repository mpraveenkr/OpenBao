from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from sqlalchemy import create_engine, text


class WatermarkStore(Protocol):
    def get_last_watermark(self, object_id: str) -> str | None:
        """Return the latest committed watermark for an object."""

    def commit_watermark(self, object_id: str, value: str, run_id: str) -> None:
        """Commit a watermark after a successful target write and audit update."""


class SQLiteWatermarkStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def get_last_watermark(self, object_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT watermark_value
                FROM ingestion_watermark
                WHERE object_id = ?
                ORDER BY committed_at_utc DESC
                LIMIT 1
                """,
                (object_id,),
            ).fetchone()
        return row[0] if row else None

    def commit_watermark(self, object_id: str, value: str, run_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM ingestion_watermark WHERE object_id = ?",
                (object_id,),
            )
            conn.execute(
                """
                INSERT INTO ingestion_watermark (
                    object_id, watermark_value, run_id, committed_at_utc
                ) VALUES (?, ?, ?, ?)
                """,
                (object_id, value, run_id, datetime.now(timezone.utc).isoformat()),
            )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ingestion_watermark (
                    object_id TEXT PRIMARY KEY,
                    watermark_value TEXT,
                    run_id TEXT,
                    committed_at_utc TEXT
                )
                """
            )
            conn.execute(
                """
                DELETE FROM ingestion_watermark
                WHERE rowid NOT IN (
                    SELECT MAX(rowid)
                    FROM ingestion_watermark
                    GROUP BY object_id
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)


class PostgresWatermarkStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self.engine = create_engine(database_url, future=True)
        self._init_db()

    def get_last_watermark(self, object_id: str) -> str | None:
        with self.engine.begin() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT watermark_value
                    FROM ingestion_watermark
                    WHERE object_id = :object_id
                    ORDER BY committed_at_utc DESC
                    LIMIT 1
                    """
                ),
                {"object_id": object_id},
            ).fetchone()
        return row[0] if row else None

    def commit_watermark(self, object_id: str, value: str, run_id: str) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM ingestion_watermark WHERE object_id = :object_id"),
                {"object_id": object_id},
            )
            conn.execute(
                text(
                    """
                    INSERT INTO ingestion_watermark (
                        object_id, watermark_value, run_id, committed_at_utc
                    ) VALUES (
                        :object_id, :watermark_value, :run_id, :committed_at_utc
                    )
                    """
                ),
                {
                    "object_id": object_id,
                    "watermark_value": value,
                    "run_id": run_id,
                    "committed_at_utc": datetime.now(timezone.utc),
                },
            )

    def _init_db(self) -> None:
        with self.engine.begin() as conn:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS ingestion_watermark (
                        object_id TEXT PRIMARY KEY,
                        watermark_value TEXT NOT NULL,
                        run_id TEXT NOT NULL,
                        committed_at_utc TIMESTAMPTZ NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE INDEX IF NOT EXISTS idx_ingestion_watermark_object_committed
                    ON ingestion_watermark (object_id, committed_at_utc DESC)
                    """
                )
            )
