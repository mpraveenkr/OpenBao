from __future__ import annotations

from argparse import Namespace

import yaml
from openpyxl import Workbook

from ingestion_framework.config.validator import SourceObjectConfig
from metadata_api.excel_importer import RequirementsWorkbookImporter
from metadata_api.repository import SourceDefinitionRepository
from metadata_api.yaml_generator import to_source_config_dict
from tools.import_source_requirements import import_folder


def test_excel_importer_maps_database_requirements(tmp_path):
    workbook_path = make_database_workbook(tmp_path / "requirements.xlsx", "sql_customers")

    payload = RequirementsWorkbookImporter().load(workbook_path)
    generated = to_source_config_dict(payload)
    validated = SourceObjectConfig.model_validate(generated)

    assert payload.extraction["db_type"] == "sql_server"
    assert len(payload.columns) == 3
    assert [column.column_name for column in payload.columns if column.primary_key] == [
        "customerid"
    ]
    assert [column.column_name for column in payload.columns if column.watermark] == [
        "load_tstz"
    ]
    assert validated.schema.columns["name"].mask_policy == "redact"
    assert generated["audit"]["primary_key"] == ["customerid"]


def test_folder_import_generates_yaml_upserts_metadata_and_reports(tmp_path):
    input_folder = tmp_path / "requirements"
    input_folder.mkdir()
    make_database_workbook(input_folder / "customers.xlsx", "sql_customers")
    make_database_workbook(input_folder / "accounts.xlsx", "sql_accounts")
    make_database_workbook(input_folder / "~$ignored.xlsx", "ignored_temp")

    output_dir = tmp_path / "configs" / "sources"
    metadata_db = tmp_path / "metadata.db"
    report_dir = tmp_path / "reports"

    report = import_folder(
        Namespace(
            input_folder=str(input_folder),
            output_dir=str(output_dir),
            metadata_db=str(metadata_db),
            dry_run=False,
            report_dir=str(report_dir),
            sheet=None,
        )
    )

    assert report["files_seen"] == 2
    assert report["sheets_processed"] == 2
    assert report["yaml_generated"] == 2
    assert report["metadata_upserts"] == 2
    assert report["failures"] == []
    assert (output_dir / "sql_customers.yaml").exists()
    assert (output_dir / "sql_accounts.yaml").exists()
    assert yaml.safe_load((output_dir / "sql_customers.yaml").read_text())["object_id"] == "sql_customers"
    assert len(SourceDefinitionRepository(metadata_db).list()) == 2
    assert report_dir.exists()


def test_folder_import_dry_run_does_not_write_outputs(tmp_path):
    input_folder = tmp_path / "requirements"
    input_folder.mkdir()
    make_database_workbook(input_folder / "customers.xlsx", "sql_customers")
    output_dir = tmp_path / "configs" / "sources"
    metadata_db = tmp_path / "metadata.db"

    report = import_folder(
        Namespace(
            input_folder=str(input_folder),
            output_dir=str(output_dir),
            metadata_db=str(metadata_db),
            dry_run=True,
            report_dir=str(tmp_path / "reports"),
            sheet=None,
        )
    )

    assert report["sheets_processed"] == 1
    assert report["yaml_generated"] == 0
    assert not output_dir.exists()
    assert not metadata_db.exists()


def make_database_workbook(workbook_path, object_id):
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Database_Customers"
    worksheet.append(["section", "field_name", "filled_value", "field_path", "notes"])
    rows = [
        ["Source", "object_id", object_id, "object_id", ""],
        ["Source", "source_system", "billing_sqlserver", "source_system", ""],
        ["Source", "source_type", "database", "source_type", ""],
        ["Source", "object_name", "customers", "object_name", ""],
        ["Source", "enabled", True, "enabled", ""],
        ["Source", "load_strategy", "incremental", "load_strategy", ""],
        ["Extraction", "db_type", "sql server", "extraction.db_type", ""],
        ["Extraction", "connection_name", "billing_readonly", "extraction.connection_name", ""],
        ["Extraction", "schema_name", "dbo", "extraction.schema_name", ""],
        ["Extraction", "table_name", "CUSTOMERS", "extraction.table_name", ""],
        ["Extraction", "incremental_column", "load_tstz", "extraction.incremental_column", ""],
        ["Schema Policy", "mode", "explicit", "schema_policy.mode", ""],
        ["Schema Policy", "allow_schema_evolution", True, "schema_policy.allow_schema_evolution", ""],
        ["Schema", "CUSTOMERID", "type=string; nullable=false; mask_policy=none", "schema.columns.customerid", "Primary key"],
        ["Schema", "NAME", "type=string; nullable=true; mask_policy=redact", "schema.columns.name", "PII"],
        ["Schema", "LOAD_TSTZ", "type=timestamp; nullable=false; mask_policy=none", "schema.columns.load_tstz", "Watermark column"],
        ["Target", "storage_name", "encrypted_bronze", "target.storage_name", ""],
        ["Target", "zone", "bronze", "target.zone", ""],
        ["Target", "format", "parquet", "target.format", ""],
        ["Target", "write_mode", "append", "target.write_mode", ""],
        ["Target", "compression", "snappy", "target.compression", ""],
        ["Target", "partition_by", "ingest_year,ingest_month,ingest_day", "target.partition_by", ""],
        ["Audit", "dq_checks", "row_count_gt_zero,primary_key_not_null", "audit.dq_checks", ""],
        ["Audit", "primary_key", "CUSTOMERID", "audit.primary_key", ""],
        ["Security", "classification", "confidential", "security.classification", ""],
        ["Security", "contains_bcsi", False, "security.contains_bcsi", ""],
        ["Security", "contains_pii", True, "security.contains_pii", ""],
        ["Security", "encryption_required", True, "security.encryption_required", ""],
        ["Security", "masking_required", True, "security.masking_required", ""],
        ["Security", "raw_payload_retention_days", 365, "security.raw_payload_retention_days", ""],
        ["Security", "access_group", "billing_data_readers", "security.access_group", ""],
    ]
    for row in rows:
        worksheet.append(row)
    workbook.save(workbook_path)
    return workbook_path
