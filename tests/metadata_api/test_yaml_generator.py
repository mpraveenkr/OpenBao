from __future__ import annotations

import yaml

from ingestion_framework.config.validator import SourceObjectConfig
from metadata_api.models import SourceDefinitionPayload
from metadata_api.yaml_generator import to_source_config_dict, to_source_yaml


def sample_payload() -> SourceDefinitionPayload:
    return SourceDefinitionPayload.model_validate(
        {
            "object_id": "sample_csv_customers_ui",
            "source_system": "sample_files",
            "source_type": "file",
            "object_name": "customers",
            "enabled": True,
            "load_strategy": "full",
            "extraction": {
                "file_type": "csv",
                "path": "data/input/customers.csv",
                "delimiter": ",",
                "header": True,
                "encoding": "utf-8",
            },
            "schema_policy": {
                "mode": "explicit",
                "column_case": "snake_case",
                "replace_spaces_with": "_",
                "allow_schema_evolution": True,
                "include_unmodeled_columns": False,
                "infer_types": False,
            },
            "columns": [
                {
                    "column_name": "customer_id",
                    "source_column_name": "Customer ID",
                    "type": "string",
                    "nullable": False,
                    "mask_policy": "none",
                    "primary_key": True,
                },
                {
                    "column_name": "updated_timestamp",
                    "source_column_name": "Updated Timestamp",
                    "type": "timestamp",
                    "nullable": True,
                    "mask_policy": "none",
                },
            ],
            "target": {
                "storage_name": "local_bronze",
                "zone": "bronze",
                "format": "parquet",
                "write_mode": "append",
                "compression": "snappy",
                "partition_by": ["ingest_year", "ingest_month", "ingest_day"],
            },
            "audit": {"dq_checks": ["row_count_gt_zero"]},
            "security": {
                "classification": "internal",
                "contains_bcsi": False,
                "contains_pii": False,
                "encryption_required": False,
                "masking_required": False,
                "raw_payload_retention_days": 30,
                "access_group": "local_ingestion_developers",
            },
        }
    )


def test_yaml_generator_outputs_framework_compatible_csv_config():
    payload = sample_payload()

    config = to_source_config_dict(payload)

    validated = SourceObjectConfig.model_validate(config)
    assert validated.object_id == "sample_csv_customers_ui"
    assert validated.schema_policy["mode"] == "explicit"
    assert validated.schema.columns["customer_id"].nullable is False
    assert config["audit"]["primary_key"] == ["customer_id"]


def test_yaml_generator_emits_parseable_yaml():
    payload = sample_payload()

    rendered = to_source_yaml(payload)

    parsed = yaml.safe_load(rendered)
    assert parsed["object_id"] == "sample_csv_customers_ui"
    assert parsed["schema"]["columns"]["updated_timestamp"]["type"] == "timestamp"
