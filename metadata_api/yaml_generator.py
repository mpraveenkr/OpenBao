from __future__ import annotations

from typing import Any

import yaml

from metadata_api.models import SourceDefinitionPayload


DEFAULT_SCHEMA_POLICY = {
    "mode": "explicit",
    "column_case": "snake_case",
    "replace_spaces_with": "_",
    "allow_schema_evolution": True,
    "include_unmodeled_columns": False,
    "infer_types": False,
}


DEFAULT_TARGET = {
    "storage_name": "local_bronze",
    "zone": "bronze",
    "format": "parquet",
    "write_mode": "append",
    "compression": "snappy",
    "partition_by": ["ingest_year", "ingest_month", "ingest_day"],
}


DEFAULT_SECURITY = {
    "classification": "internal",
    "contains_bcsi": False,
    "contains_pii": False,
    "encryption_required": False,
    "masking_required": False,
    "raw_payload_retention_days": 30,
    "access_group": "local_ingestion_developers",
}


def to_source_config_dict(definition: SourceDefinitionPayload) -> dict[str, Any]:
    schema_policy = DEFAULT_SCHEMA_POLICY | definition.schema_policy
    target = DEFAULT_TARGET | definition.target
    security = DEFAULT_SECURITY | definition.security
    audit = build_audit(definition)

    source_config: dict[str, Any] = {
        "object_id": definition.object_id,
        "source_system": definition.source_system,
        "source_type": definition.source_type,
        "object_name": definition.object_name,
        "enabled": definition.enabled,
        "load_strategy": definition.load_strategy,
        "extraction": prune_empty(definition.extraction),
        "schema_policy": prune_empty(schema_policy),
        "schema": {"columns": build_schema_columns(definition)},
        "target": normalize_target(target),
        "audit": audit,
        "security": prune_empty(security),
    }
    return source_config


def to_source_yaml(definition: SourceDefinitionPayload) -> str:
    return yaml.safe_dump(
        to_source_config_dict(definition),
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    )


def build_schema_columns(definition: SourceDefinitionPayload) -> dict[str, dict[str, Any]]:
    columns: dict[str, dict[str, Any]] = {}
    for column in definition.columns:
        entry = {
            "type": column.type,
            "nullable": column.nullable,
            "mask_policy": column.mask_policy or "none",
        }
        if column.source_column_name:
            entry["source_column_name"] = column.source_column_name
        columns[column.column_name] = prune_empty(entry)
    return columns


def build_audit(definition: SourceDefinitionPayload) -> dict[str, Any]:
    checks = definition.audit.get("dq_checks", ["row_count_gt_zero"])
    if isinstance(checks, str):
        checks = [item.strip() for item in checks.split(",") if item.strip()]

    primary_key = [
        column.column_name for column in definition.columns if column.primary_key
    ] or definition.audit.get("primary_key", [])
    if isinstance(primary_key, str):
        primary_key = [item.strip() for item in primary_key.split(",") if item.strip()]

    audit = dict(definition.audit)
    audit["dq_checks"] = checks
    audit["primary_key"] = primary_key
    return prune_empty(audit)


def normalize_target(target: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(target)
    partition_by = normalized.get("partition_by", [])
    if isinstance(partition_by, str):
        partition_by = [item.strip() for item in partition_by.split(",") if item.strip()]
    normalized["partition_by"] = partition_by
    return prune_empty(normalized)


def prune_empty(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: prune_empty(item)
            for key, item in value.items()
            if item is not None and item != ""
        }
    if isinstance(value, list):
        return [prune_empty(item) for item in value if item is not None and item != ""]
    return value
