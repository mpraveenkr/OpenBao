from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExtractionConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    file_type: str | None = None
    path: str | None = None
    delimiter: str = ","
    header: bool = True
    encoding: str = "utf-8"
    db_type: str | None = None
    connection_name: str | None = None
    schema_name: str | None = None
    table_name: str | None = None
    query: str | None = None
    incremental_column: str | None = None
    watermark_type: str | None = None
    fetch_size: int | None = None
    base_url: str | None = None
    endpoint: str | None = None
    method: str | None = None
    auth_type: str | None = None
    response_record_path: str | None = None


class ColumnConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: Literal[
        "string",
        "integer",
        "bigint",
        "decimal",
        "float",
        "boolean",
        "date",
        "timestamp",
    ]
    nullable: bool = True
    mask_policy: str = "none"


class SchemaConfig(BaseModel):
    columns: dict[str, ColumnConfig] = Field(default_factory=dict)


class TargetConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    storage_name: str
    zone: str
    format: str
    write_mode: str = "append"
    compression: str = "snappy"
    partition_by: list[str] = Field(default_factory=list)


class SecurityConfig(BaseModel):
    classification: str
    contains_bcsi: bool = False
    contains_pii: bool = False
    encryption_required: bool = False
    masking_required: bool = False
    raw_payload_retention_days: int
    access_group: str


class SourceObjectConfig(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    object_id: str
    source_system: str
    source_type: str
    object_name: str
    enabled: bool = True
    load_strategy: str
    extraction: ExtractionConfig
    schema_policy: dict[str, Any] = Field(default_factory=dict)
    schema_: SchemaConfig = Field(default_factory=SchemaConfig, alias="schema")
    target: TargetConfig
    audit: dict[str, Any] = Field(default_factory=dict)
    security: SecurityConfig

    @property
    def schema(self) -> SchemaConfig:
        return self.schema_

    @model_validator(mode="after")
    def validate_extraction_for_source_type(self) -> "SourceObjectConfig":
        extraction = self.extraction
        if self.source_type == "file":
            if not extraction.file_type or not extraction.path:
                raise ValueError("File source requires extraction.file_type and extraction.path")
        elif self.source_type == "database":
            if not extraction.db_type or not extraction.connection_name:
                raise ValueError(
                    "Database source requires extraction.db_type and extraction.connection_name"
                )
            if not extraction.table_name and not extraction.query:
                raise ValueError("Database source requires extraction.table_name or extraction.query")
        elif self.source_type == "api":
            if not extraction.base_url or not extraction.endpoint:
                raise ValueError("API source requires extraction.base_url and extraction.endpoint")
        else:
            raise ValueError(f"Unsupported source_type: {self.source_type}")
        return self


class EncryptionConfig(BaseModel):
    supported: bool = False
    mode: str = "none"


class StorageConfig(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    base_path: str | None = None
    bucket: str | None = None
    base_prefix: str = ""
    endpoint_url: str | None = None
    access_key_ref: str | None = None
    secret_key_ref: str | None = None
    region: str = "us-east-1"
    # Azure Data Lake Storage Gen2. tenant_id and client_id are identifiers and
    # may be inline; the client secret and account key must be OpenBao
    # references so a credential cannot be committed to a config file.
    account_name: str | None = None
    filesystem: str | None = None
    auth_method: str | None = None
    tenant_id: str | None = None
    client_id: str | None = None
    client_secret_ref: str | None = None
    account_key_ref: str | None = None
    encryption: EncryptionConfig = Field(default_factory=EncryptionConfig)

    @model_validator(mode="after")
    def validate_storage_fields(self) -> "StorageConfig":
        if self.type == "local":
            if not self.base_path:
                raise ValueError("Local storage requires base_path")
        elif self.type in {"s3_compatible", "s3"}:
            self._require_fields(
                ["bucket", "endpoint_url", "access_key_ref", "secret_key_ref"],
                "S3-compatible storage",
            )
        elif self.type in {"adls_gen2", "adls"}:
            self._validate_adls_fields()
        else:
            raise ValueError(f"Unsupported storage type: {self.type}")
        return self

    def _validate_adls_fields(self) -> None:
        self._require_fields(["account_name", "filesystem"], "ADLS Gen2 storage")

        auth_method = (self.auth_method or "service_principal").strip()
        if auth_method == "service_principal":
            self._require_fields(
                ["tenant_id", "client_id", "client_secret_ref"],
                "ADLS Gen2 service principal auth",
            )
        elif auth_method == "account_key":
            self._require_fields(["account_key_ref"], "ADLS Gen2 account key auth")
        else:
            raise ValueError(
                f"Unsupported ADLS Gen2 auth_method: {auth_method}. "
                "Supported values are: service_principal, account_key"
            )

    def _require_fields(self, fields: list[str], label: str) -> None:
        missing = [field for field in fields if not getattr(self, field)]
        if missing:
            raise ValueError(f"{label} requires: " + ", ".join(missing))


class StorageRegistryConfig(BaseModel):
    storages: dict[str, StorageConfig]


class SecurityPolicyValidator:
    """Validates metadata controls before extraction begins."""

    @staticmethod
    def validate(source: SourceObjectConfig, storage: StorageConfig) -> None:
        security = source.security
        if security.contains_bcsi and security.encryption_required:
            if not storage.encryption.supported:
                raise ValueError(
                    "Security policy violation: BCSI source requires storage encryption support."
                )

        if security.contains_bcsi and storage.type == "local" and not storage.encryption.supported:
            raise ValueError(
                "Security policy violation: BCSI source cannot target unencrypted local storage."
            )

        if security.masking_required:
            has_mask_policy = any(
                column.mask_policy and column.mask_policy.lower() != "none"
                for column in source.schema.columns.values()
            )
            if not has_mask_policy:
                raise ValueError(
                    "Security policy violation: masking_required=true needs at least one non-none mask_policy."
                )
