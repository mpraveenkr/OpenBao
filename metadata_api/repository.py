from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from metadata_api.models import (
    SourceDefinitionPayload,
    SourceDefinitionRecord,
    utc_now,
)


class SourceDefinitionRepository:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def list(self) -> list[SourceDefinitionRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, object_id, source_system, source_type, object_name,
                       status, definition_json, created_by, updated_by,
                       created_at, updated_at
                FROM source_definitions
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
        return [self._to_record(row) for row in rows]

    def get(self, definition_id: int) -> SourceDefinitionRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, object_id, source_system, source_type, object_name,
                       status, definition_json, created_by, updated_by,
                       created_at, updated_at
                FROM source_definitions
                WHERE id = ?
                """,
                (definition_id,),
            ).fetchone()
        return self._to_record(row) if row else None

    def create(
        self,
        payload: SourceDefinitionPayload,
        created_by: str,
        status: str = "DRAFT",
    ) -> SourceDefinitionRecord:
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO source_definitions (
                    object_id, source_system, source_type, object_name,
                    status, definition_json, created_by, updated_by,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.object_id,
                    payload.source_system,
                    payload.source_type,
                    payload.object_name,
                    status,
                    payload.model_dump_json(),
                    created_by,
                    created_by,
                    now,
                    now,
                ),
            )
            definition_id = int(cursor.lastrowid)
        record = self.get(definition_id)
        if record is None:
            raise RuntimeError("Created source definition could not be loaded")
        return record

    def update(
        self,
        definition_id: int,
        payload: SourceDefinitionPayload,
        updated_by: str,
        status: str = "DRAFT",
    ) -> SourceDefinitionRecord | None:
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE source_definitions
                SET object_id = ?, source_system = ?, source_type = ?,
                    object_name = ?, status = ?, definition_json = ?,
                    updated_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.object_id,
                    payload.source_system,
                    payload.source_type,
                    payload.object_name,
                    status,
                    payload.model_dump_json(),
                    updated_by,
                    now,
                    definition_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
        return self.get(definition_id)

    def delete(self, definition_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM source_definitions WHERE id = ?", (definition_id,))
        return cursor.rowcount > 0

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS source_definitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    object_id TEXT NOT NULL,
                    source_system TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    object_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    updated_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS ux_source_definitions_object_id
                ON source_definitions(object_id)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    @staticmethod
    def _to_record(row: sqlite3.Row | tuple) -> SourceDefinitionRecord:
        return SourceDefinitionRecord(
            id=row[0],
            object_id=row[1],
            source_system=row[2],
            source_type=row[3],
            object_name=row[4],
            status=row[5],
            definition=SourceDefinitionPayload.model_validate(json.loads(row[6])),
            created_by=row[7],
            updated_by=row[8],
            created_at=row[9],
            updated_at=row[10],
        )
