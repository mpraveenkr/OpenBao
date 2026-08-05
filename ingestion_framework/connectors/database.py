from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from collections.abc import Iterator
from typing import Any, Callable
from urllib.parse import quote_plus

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine

from ingestion_framework.config.validator import ColumnConfig, SchemaConfig
from ingestion_framework.normalizers.columns import ColumnNormalizer
from ingestion_framework.secrets import resolve_env_or_secret


EngineFactory = Callable[[Any, Path], Engine]


@dataclass(frozen=True)
class DatabaseExtractResult:
    frame: pd.DataFrame
    runtime_schema: SchemaConfig


@dataclass(frozen=True)
class DatabaseChunkExtractResult:
    chunks: Iterator[pd.DataFrame]
    runtime_schema: SchemaConfig


class DatabaseExtractor:
    """Extract database rows and runtime schema using source-object metadata."""

    def __init__(self, engine_factory: EngineFactory | None = None) -> None:
        self.engine_factory = engine_factory or create_database_engine

    def extract(self, source: Any, base_dir: Path, watermark_store: Any | None = None) -> DatabaseExtractResult:
        validate_load_strategy(source)

        engine = self.engine_factory(source.extraction, base_dir)
        sql, params = build_sql_and_params(source, watermark_store)

        with engine.connect() as connection:
            extracted = pd.read_sql_query(sql, connection, params=params)

        normalized = normalize_database_frame(extracted, source)
        runtime_schema = build_runtime_schema(source, engine, extracted, normalized)
        return DatabaseExtractResult(
            frame=normalized,
            runtime_schema=runtime_schema,
        )

    def extract_chunks(
        self,
        source: Any,
        base_dir: Path,
        watermark_store: Any | None = None,
    ) -> DatabaseChunkExtractResult:
        """Extract database rows as normalized DataFrame chunks.

        The returned iterator owns an open database connection until it is fully
        consumed or closed by the generator finalizer.
        """
        validate_load_strategy(source)
        fetch_size = int(getattr(source.extraction, "fetch_size", None) or 0)
        if fetch_size <= 0:
            raise ValueError("Database chunk extraction requires extraction.fetch_size")

        engine = self.engine_factory(source.extraction, base_dir)
        sql, params = build_sql_and_params(source, watermark_store)
        connection = engine.connect()
        chunk_iterator = iter(
            pd.read_sql_query(
                sql,
                connection,
                params=params,
                chunksize=fetch_size,
            )
        )
        try:
            first_chunk = next(chunk_iterator)
        except StopIteration:
            first_chunk = pd.DataFrame()

        normalized_first = normalize_database_frame(first_chunk, source)
        runtime_schema = build_runtime_schema(source, engine, first_chunk, normalized_first)

        def normalized_chunks() -> Iterator[pd.DataFrame]:
            try:
                if not first_chunk.empty or list(first_chunk.columns):
                    yield normalized_first
                for chunk in chunk_iterator:
                    yield normalize_database_frame(chunk, source)
            finally:
                connection.close()

        return DatabaseChunkExtractResult(
            chunks=normalized_chunks(),
            runtime_schema=runtime_schema,
        )


def validate_load_strategy(source: Any) -> None:
    has_watermark = bool(get_watermark_column(source))
    if source.load_strategy == "incremental" and not has_watermark:
        raise ValueError(
            f"{source.object_id}: incremental database load requires a watermark column"
        )


def build_sql_and_params(source: Any, watermark_store: Any | None = None) -> tuple[Any, dict[str, Any]]:
    extraction = source.extraction
    query = str(extraction.query or "").strip()
    params: dict[str, Any] = {}

    if source.load_strategy == "incremental":
        watermark_column = get_watermark_column(source)
        last_watermark = get_last_watermark(source, watermark_store)
        params["last_watermark"] = last_watermark
        if query:
            return text(strip_trailing_semicolon(query)), params
        table_ref = build_table_reference(extraction)
        return (
            text(
                f"SELECT * FROM {table_ref} "
                f"WHERE {quote_identifier(watermark_column)} > :last_watermark"
            ),
            params,
        )

    if query:
        return text(strip_trailing_semicolon(query)), params
    return text(f"SELECT * FROM {build_table_reference(extraction)}"), params


def get_last_watermark(source: Any, watermark_store: Any | None = None) -> str:
    if watermark_store:
        value = watermark_store.get_last_watermark(source.object_id)
        if value:
            return value
    watermark = get_extra(source.extraction, "watermark", {}) or {}
    initial = watermark.get("initial_value")
    if initial:
        return str(initial)
    watermark_type = watermark.get("value_type") or source.extraction.watermark_type
    if str(watermark_type).lower() in {"integer", "bigint"}:
        return "0"
    if str(watermark_type).lower() == "date":
        return "1900-01-01"
    return "1900-01-01T00:00:00Z"


def get_watermark_column(source: Any) -> str:
    watermark = get_extra(source.extraction, "watermark", {}) or {}
    return (
        str(watermark.get("column") or "").strip()
        or str(source.extraction.incremental_column or "").strip()
    )


def build_table_reference(extraction: Any) -> str:
    table_name = str(extraction.table_name or "").strip()
    if not table_name:
        raise ValueError("Database extraction requires table_name when query is not provided")
    schema_name = str(extraction.schema_name or "").strip()
    db_type = str(extraction.db_type or "").lower()
    if schema_name and db_type not in {"sqlite", "sqlite3"}:
        return f"{quote_identifier(schema_name)}.{quote_identifier(table_name)}"
    return quote_identifier(table_name)


def quote_identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"Unsafe database identifier: {value}")
    return value


def strip_trailing_semicolon(query: str) -> str:
    return query.rstrip().removesuffix(";").rstrip()


def normalize_database_frame(frame: pd.DataFrame, source: Any) -> pd.DataFrame:
    result = frame.copy()
    normalizer = ColumnNormalizer()
    original_columns = list(result.columns)
    normalized_columns = normalizer.normalize(original_columns)
    result.columns = normalized_columns

    rename_map = {}
    for target_column, column_config in source.schema.columns.items():
        source_column_name = get_extra(column_config, "source_column_name")
        if not source_column_name:
            continue
        normalized_source = normalizer.normalize([source_column_name])[0]
        if normalized_source in result.columns and normalized_source != target_column:
            rename_map[normalized_source] = target_column
    if rename_map:
        result = result.rename(columns=rename_map)
    return result


def build_runtime_schema(
    source: Any,
    engine: Engine,
    extracted: pd.DataFrame,
    normalized: pd.DataFrame,
) -> SchemaConfig:
    mode = str(source.schema_policy.get("mode") or "explicit")
    include_unmodeled = bool(source.schema_policy.get("include_unmodeled_columns"))
    infer_types = bool(source.schema_policy.get("infer_types"))
    type_discovery = str(source.schema_policy.get("type_discovery") or "").lower()
    should_discover = (
        mode in {"infer", "hybrid"}
        or include_unmodeled
        or infer_types
        or type_discovery == "source_metadata"
    )

    if not should_discover:
        return source.schema

    discovered = discover_source_columns(source, engine, extracted)
    runtime_columns: dict[str, ColumnConfig] = {}
    normalizer = ColumnNormalizer()

    for column in discovered:
        source_column_name = str(column["name"])
        normalized_name = normalizer.normalize([source_column_name])[0]
        framework_type = column.get("framework_type") or infer_pandas_type(
            extracted[source_column_name] if source_column_name in extracted.columns else None
        )
        runtime_columns[normalized_name] = ColumnConfig.model_validate(
            {
                "type": framework_type,
                "nullable": column.get("nullable", True),
                "mask_policy": "none",
                "source_column_name": source_column_name,
            }
        )

    if not runtime_columns:
        for column_name in normalized.columns:
            runtime_columns[column_name] = ColumnConfig.model_validate(
                {
                    "type": infer_pandas_type(normalized[column_name]),
                    "nullable": True,
                    "mask_policy": "none",
                    "source_column_name": column_name,
                }
            )

    for target_column, override in source.schema.columns.items():
        source_column_name = get_extra(override, "source_column_name")
        if source_column_name:
            discovered_name = normalizer.normalize([source_column_name])[0]
            runtime_columns.pop(discovered_name, None)
        runtime_columns[target_column] = override

    return SchemaConfig(columns=runtime_columns)


def discover_source_columns(
    source: Any, engine: Engine, extracted: pd.DataFrame
) -> list[dict[str, Any]]:
    extraction = source.extraction
    db_type = normalize_db_type(str(extraction.db_type or ""))
    provider = metadata_provider_for(db_type)
    if provider is None:
        return discover_columns_from_result(extracted)
    return provider(source, engine, extracted)


def metadata_provider_for(db_type: str):
    if db_type in {"sqlite", "sqlite3"}:
        return discover_sqlite_columns
    if db_type in {"sql_server", "mssql"}:
        return discover_sql_server_columns
    if db_type in {"postgres", "postgresql"}:
        return discover_postgres_columns
    return None


def discover_sqlite_columns(
    source: Any, engine: Engine, extracted: pd.DataFrame
) -> list[dict[str, Any]]:
    return discover_columns_with_inspector(
        source=source,
        engine=engine,
        extracted=extracted,
        default_schema=None,
        mapper=map_sqlite_type,
    )


def discover_sql_server_columns(
    source: Any, engine: Engine, extracted: pd.DataFrame
) -> list[dict[str, Any]]:
    return discover_columns_with_inspector(
        source=source,
        engine=engine,
        extracted=extracted,
        default_schema="dbo",
        mapper=map_sql_server_type,
    )


def discover_postgres_columns(
    source: Any, engine: Engine, extracted: pd.DataFrame
) -> list[dict[str, Any]]:
    return discover_columns_with_inspector(
        source=source,
        engine=engine,
        extracted=extracted,
        default_schema="public",
        mapper=map_postgres_type,
    )


def discover_columns_with_inspector(
    source: Any,
    engine: Engine,
    extracted: pd.DataFrame,
    default_schema: str | None,
    mapper: Callable[[Any], str],
) -> list[dict[str, Any]]:
    extraction = source.extraction
    table_name = str(extraction.table_name or "").strip()
    schema_name = str(extraction.schema_name or "").strip() or default_schema
    if table_name:
        try:
            inspector = inspect(engine)
            return [
                {
                    "name": column["name"],
                    "nullable": column.get("nullable", True),
                    "framework_type": mapper(column.get("type")),
                    "source_type": str(column.get("type") or ""),
                }
                for column in inspector.get_columns(table_name, schema=schema_name)
            ]
        except Exception:
            # Query result columns are still a safe fallback for views/custom SQL.
            pass
    return discover_columns_from_result(extracted)


def discover_columns_from_result(extracted: pd.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "name": column_name,
            "nullable": True,
            "framework_type": infer_pandas_type(extracted[column_name]),
            "source_type": str(extracted[column_name].dtype),
        }
        for column_name in extracted.columns
    ]


def map_sql_server_type(db_type: Any) -> str:
    type_name = str(db_type or "").lower()
    if "bigint" in type_name:
        return "bigint"
    if any(token in type_name for token in ["int", "smallint", "tinyint"]):
        return "integer"
    if any(token in type_name for token in ["decimal", "numeric", "money", "smallmoney"]):
        return "decimal"
    if any(token in type_name for token in ["float", "real", "double"]):
        return "float"
    if any(token in type_name for token in ["bit", "bool"]):
        return "boolean"
    if any(token in type_name for token in ["datetime", "datetime2", "smalldatetime", "datetimeoffset", "timestamp"]):
        return "timestamp"
    if re.search(r"\bdate\b", type_name):
        return "date"
    return "string"


def map_postgres_type(db_type: Any) -> str:
    type_name = str(db_type or "").lower()
    if "bigint" in type_name:
        return "bigint"
    if any(token in type_name for token in ["integer", "smallint", "serial"]):
        return "integer"
    if any(token in type_name for token in ["numeric", "decimal", "money"]):
        return "decimal"
    if any(token in type_name for token in ["double", "real", "float"]):
        return "float"
    if "bool" in type_name:
        return "boolean"
    if any(token in type_name for token in ["timestamp", "time with time zone", "time without time zone"]):
        return "timestamp"
    if re.search(r"\bdate\b", type_name):
        return "date"
    return "string"


def map_sqlite_type(db_type: Any) -> str:
    type_name = str(db_type or "").lower()
    if "bigint" in type_name:
        return "bigint"
    if any(token in type_name for token in ["int", "integer"]):
        return "integer"
    if any(token in type_name for token in ["real", "double", "float"]):
        return "float"
    if any(token in type_name for token in ["numeric", "decimal"]):
        return "decimal"
    if "bool" in type_name:
        return "boolean"
    if "datetime" in type_name or "timestamp" in type_name:
        return "timestamp"
    if re.search(r"\bdate\b", type_name):
        return "date"
    return "string"


def infer_pandas_type(series: pd.Series | None) -> str:
    if series is None:
        return "string"
    dtype = str(series.dtype).lower()
    if "datetime" in dtype:
        return "timestamp"
    if dtype in {"bool", "boolean"}:
        return "boolean"
    if "int" in dtype:
        return "bigint"
    if "float" in dtype:
        return "float"
    return "string"


def get_max_watermark_value(frame: pd.DataFrame, source: Any) -> str | None:
    if source.load_strategy != "incremental":
        return None
    watermark_column = get_watermark_column(source)
    if not watermark_column:
        return None
    normalized_watermark = ColumnNormalizer().normalize([watermark_column])[0]
    candidates = [watermark_column, normalized_watermark]
    for column_name in source.schema.columns:
        column_config = source.schema.columns[column_name]
        source_column_name = get_extra(column_config, "source_column_name")
        if source_column_name and ColumnNormalizer().normalize([source_column_name])[0] == normalized_watermark:
            candidates.append(column_name)
    for candidate in candidates:
        if candidate in frame.columns and not frame[candidate].dropna().empty:
            value = frame[candidate].max()
            if hasattr(value, "isoformat"):
                return value.isoformat()
            return str(value)
    return None


def create_database_engine(extraction: Any, base_dir: Path) -> Engine:
    connection_string = get_extra(extraction, "connection_string")
    if connection_string:
        return create_engine(resolve_sqlite_connection_string(str(connection_string), base_dir))

    db_type = str(extraction.db_type or "").lower().replace(" ", "_")
    if db_type in {"sqlite", "sqlite3"}:
        database_name = str(extraction.database_name or "").strip()
        if not database_name:
            raise ValueError("SQLite database extraction requires database_name or connection_string")
        database_path = Path(database_name)
        if not database_path.is_absolute():
            database_path = base_dir / database_path
        return create_engine(f"sqlite:///{database_path}")

    if db_type in {"sql_server", "mssql"}:
        return create_sql_server_engine(extraction)

    raise NotImplementedError(f"Unsupported database type: {extraction.db_type}")


def resolve_sqlite_connection_string(connection_string: str, base_dir: Path) -> str:
    if not connection_string.startswith("sqlite:///"):
        return connection_string
    path = connection_string.removeprefix("sqlite:///")
    if path == ":memory:" or Path(path).is_absolute():
        return connection_string
    return "sqlite:///" + str(base_dir / path)


def create_sql_server_engine(extraction: Any) -> Engine:
    connection_name = str(extraction.connection_name or "").strip()
    prefix = normalize_identifier(connection_name).upper()
    host = os.getenv(f"{prefix}_HOST")
    port = os.getenv(f"{prefix}_PORT", "1433")
    database = os.getenv(f"{prefix}_DATABASE") or str(extraction.database_name or "").strip()
    username_location = get_extra(extraction, "username_secret_ref") or sql_server_secret_ref(
        connection_name, "username"
    )
    password_location = get_extra(extraction, "password_secret_ref") or sql_server_secret_ref(
        connection_name, "password"
    )
    username = resolve_env_or_secret(
        username_location,
        label=f"{connection_name or prefix} SQL Server username",
    )
    password = resolve_env_or_secret(
        password_location,
        label=f"{connection_name or prefix} SQL Server password",
    )
    driver = os.getenv(f"{prefix}_DRIVER", "ODBC Driver 18 for SQL Server")

    missing = [
        name
        for name, value in {
            f"{prefix}_HOST": host,
            f"{prefix}_DATABASE": database,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(
            "SQL Server connection environment variable(s) are not set: "
            + ", ".join(missing)
        )

    odbc = (
        f"DRIVER={{{driver}}};"
        f"SERVER={host},{port};"
        f"DATABASE={database};"
        f"UID={username};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=no;"
    )
    return create_engine(f"mssql+pyodbc:///?odbc_connect={quote_plus(odbc)}")


def sql_server_secret_ref(connection_name: str, field: str) -> str:
    normalized = normalize_identifier(connection_name)
    if not normalized:
        raise ValueError("SQL Server extraction requires connection_name or explicit secret refs")
    return f"openbao:secret/data/ingestion-framework/database/{normalized}#{field}"


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_db_type(value: str) -> str:
    return value.lower().replace(" ", "_")


def get_extra(model: Any, key: str, default: Any = None) -> Any:
    if isinstance(model, dict):
        return model.get(key, default)
    if hasattr(model, key):
        value = getattr(model, key)
        if value is not None:
            return value
    extra = getattr(model, "model_extra", None) or {}
    return extra.get(key, default)
