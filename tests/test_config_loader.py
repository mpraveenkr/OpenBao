from __future__ import annotations

import pytest
import yaml
from pydantic import ValidationError

from ingestion_framework.config.loader import ConfigLoader
from ingestion_framework.config.validator import SecurityPolicyValidator


def test_config_loader_loads_sample_config():
    config = ConfigLoader().load_source("configs/sources/sample_csv_customers.yaml")

    assert config.object_id == "sample_csv_customers"
    assert config.extraction.path == "data/input/customers.csv"
    assert config.security.classification == "internal"


def test_missing_required_config_fields_fail_validation(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("object_id: missing_required\n", encoding="utf-8")

    with pytest.raises(ValidationError):
        ConfigLoader().load_source(path)


def test_internal_non_bcsi_source_can_write_to_unencrypted_storage():
    source = ConfigLoader().load_source("configs/sources/sample_csv_customers.yaml")
    storage = ConfigLoader().load_storage("configs/storage.yaml").storages["local_bronze"]

    SecurityPolicyValidator.validate(source, storage)


def test_bcsi_source_fails_when_storage_encryption_not_supported(tmp_path):
    source_data = yaml.safe_load(open("configs/sources/sample_csv_customers.yaml", encoding="utf-8"))
    source_data["security"]["contains_bcsi"] = True
    source_data["security"]["encryption_required"] = True
    path = tmp_path / "bcsi.yaml"
    path.write_text(yaml.safe_dump(source_data), encoding="utf-8")

    source = ConfigLoader().load_source(path)
    storage = ConfigLoader().load_storage("configs/storage.yaml").storages["local_bronze"]

    with pytest.raises(ValueError, match="BCSI source"):
        SecurityPolicyValidator.validate(source, storage)


def test_masking_required_fails_without_mask_policy(tmp_path):
    source_data = yaml.safe_load(open("configs/sources/sample_csv_customers.yaml", encoding="utf-8"))
    source_data["security"]["masking_required"] = True
    path = tmp_path / "masking.yaml"
    path.write_text(yaml.safe_dump(source_data), encoding="utf-8")

    source = ConfigLoader().load_source(path)
    storage = ConfigLoader().load_storage("configs/storage.yaml").storages["local_bronze"]

    with pytest.raises(ValueError, match="masking_required"):
        SecurityPolicyValidator.validate(source, storage)


def test_config_loader_accepts_database_source_config():
    config = ConfigLoader().load_source(
        "configs/sources/itron_mv90_cmmastst_customer_master.yaml"
    )

    assert config.source_type == "database"
    assert config.extraction.db_type == "sql_server"
    assert config.extraction.table_name == "CMMASTST"
    assert len(config.schema.columns) == 88
