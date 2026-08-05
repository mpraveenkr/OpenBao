from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


DataType = Literal[
    "string",
    "integer",
    "bigint",
    "decimal",
    "float",
    "boolean",
    "date",
    "timestamp",
]


class ColumnDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    column_name: str
    source_column_name: str | None = None
    type: DataType = "string"
    nullable: bool = True
    mask_policy: str = "none"
    primary_key: bool = False
    watermark: bool = False
    notes: str | None = None

    @field_validator("column_name")
    @classmethod
    def column_name_required(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("column_name is required")
        return cleaned


class SourceDefinitionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    object_id: str
    source_system: str
    source_type: Literal["file", "database", "api"]
    object_name: str
    enabled: bool = True
    load_strategy: Literal["full", "incremental", "snapshot"] = "full"
    extraction: dict[str, Any] = Field(default_factory=dict)
    schema_policy: dict[str, Any] = Field(default_factory=dict)
    columns: list[ColumnDefinition] = Field(default_factory=list)
    target: dict[str, Any] = Field(default_factory=dict)
    audit: dict[str, Any] = Field(default_factory=dict)
    security: dict[str, Any] = Field(default_factory=dict)
    storage: dict[str, Any] | None = None

    @field_validator("object_id", "source_system", "object_name")
    @classmethod
    def required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("value is required")
        return cleaned


class SourceDefinitionCreate(BaseModel):
    payload: SourceDefinitionPayload
    created_by: str = "local_user"


class SourceDefinitionUpdate(BaseModel):
    payload: SourceDefinitionPayload
    updated_by: str = "local_user"


class SourceDefinitionRecord(BaseModel):
    id: int
    object_id: str
    source_system: str
    source_type: str
    object_name: str
    status: str
    definition: SourceDefinitionPayload
    created_by: str
    updated_by: str
    created_at: str
    updated_at: str


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
