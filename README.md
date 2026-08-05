# Ingestion Framework

Production-style, metadata-driven ingestion framework for Bronze-layer ingestion.

## MVP Scope

The framework supports metadata-driven ingestion for file/CSV, API, and database sources:

source YAML -> extraction -> column normalization -> type mapping -> ingestion metadata columns -> Parquet -> `_manifest.json` -> audit/watermark persistence.

Local development can use SQLite and local disk. The single-node Airflow deployment uses Airflow, MinIO/S3-compatible storage, and Postgres-backed audit/watermark persistence.

## Framework Architecture

The code separates source access from ingestion orchestration:

- `ingestion_framework/connectors/` contains source-specific extractors such as CSV file, API, and database extraction.
- `ingestion_framework/processors/` contains Bronze ingestion workflows that call connectors, normalize data, apply framework types, add ingestion metadata, write Parquet, write manifests, and update audit/watermark state.
- `ingestion_framework/writers/format/` contains format writers, such as Parquet serialization.
- `ingestion_framework/writers/storage/` contains target storage writers, such as local filesystem and S3-compatible object storage.

This keeps onboarding metadata-driven while making each layer easier to test and extend.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## Run Tests

```bash
pytest
```

## Run Sample Ingestion

```bash
python -m ingestion_framework.cli run-object \
  --config configs/sources/sample_csv_customers.yaml \
  --storage configs/storage.yaml \
  --audit-db data/audit/ingestion_audit.db
```

After editable install, the console script is also available:

```bash
ingest-object run-object \
  --config configs/sources/sample_csv_customers.yaml \
  --storage configs/storage.yaml \
  --audit-db data/audit/ingestion_audit.db
```

## Expected Output

```text
data/output/
└── bronze/
    └── source_type=file/
        └── source_system=sample_files/
            └── object=customers/
                └── ingest_year=YYYY/
                    └── ingest_month=MM/
                        └── ingest_day=DD/
                            └── run_id=<run_id>/
                                ├── part-00001.parquet
                                └── _manifest.json
```

SQLite audit and watermark records are written to `data/audit/ingestion_audit.db`.

## Audit and Watermark Persistence

The `--audit-db` argument accepts either a local SQLite path or a Postgres SQLAlchemy URL.

Local development can continue to use SQLite:

```bash
ingest-object run-object \
  --config configs/sources/sample_csv_customers.yaml \
  --storage configs/storage.yaml \
  --audit-db data/audit/ingestion_audit.db
```

Airflow or production-style deployments can use Postgres:

```bash
export OPENBAO_ADDR='https://openbao.example.com:8200'
export OPENBAO_TOKEN_FILE='/run/secrets/openbao_token'
export INGESTION_AUDIT_DB_URL='openbao:secret/data/ingestion-framework/audit#url'

ingest-object run-object \
  --config configs/sources/sample_csv_customers.yaml \
  --storage configs/storage_minio.yaml \
  --audit-db env:INGESTION_AUDIT_DB_URL
```

The framework creates the audit and watermark tables automatically if they do not exist.

## OpenBao Secrets

Runtime credentials should be stored in OpenBao, not in `.env` files. The
framework resolves secret references in this form:

```text
openbao:secret/data/ingestion-framework/minio#access_key
```

For KV v2, include `data/` in the path. Configure the runtime with
`OPENBAO_ADDR` and preferably `OPENBAO_TOKEN_FILE`; `OPENBAO_TOKEN`, `BAO_TOKEN`,
and `VAULT_TOKEN` are supported for local development but are not the preferred
deployment pattern.

Examples:

```yaml
# configs/storage_minio.yaml
endpoint_url: http://minio:9000
access_key_ref: openbao:secret/data/ingestion-framework/minio#access_key
secret_key_ref: openbao:secret/data/ingestion-framework/minio#secret_key
```

```yaml
# API source extraction
auth_type: api_key_header
api_key_header_name: Ocp-Apim-Subscription-Key
api_key_secret_ref: openbao:secret/data/ingestion-framework/api/pjm#subscription_key
```

```yaml
# SQL Server source extraction
username_secret_ref: openbao:secret/data/ingestion-framework/database/itron_mv90_sqlserver_readonly#username
password_secret_ref: openbao:secret/data/ingestion-framework/database/itron_mv90_sqlserver_readonly#password
```

## Airflow DAG Generation

Generate the safe default subset:

```bash
python tools/generate_airflow_dags.py --validate
```

The generator defaults to the `single-node-airflow` profile and writes DAGs under `deploy/single-node-airflow/dags/generated/`. Generated DAGs call the existing CLI and use Postgres-backed audit/watermark state through:

```bash
--audit-db env:INGESTION_AUDIT_DB_URL
```

Each generated DAG defaults to `max_active_runs=1` so two runs of the same object do not race against the same watermark.

Source YAML files can optionally include orchestration metadata:

```yaml
orchestration:
  load_type: ongoing
  schedule: "0 6 * * *"
  start_date: "2026-01-01"
  catchup: false
  retries: 2
  retry_delay_minutes: 5
  max_active_runs: 1
  pool: ingestion_api_pool
  priority_weight: 5
  tags:
    - bronze
    - api
```

Use `load_type: one_time` for historical one-time loads. Lawson full-load objects are inferred as `one_time` by the generator unless explicitly overridden in YAML.

To intentionally generate compact database DAGs, use both gates:

```bash
python tools/generate_airflow_dags.py \
  --scan-all \
  --include-all-databases \
  --validate
```

To generate only ongoing sources:

```bash
python tools/generate_airflow_dags.py --scan-all --load-type ongoing --validate
```

## Security Metadata

Source configs include NERC-aligned security metadata such as classification, BCSI/PII flags, encryption requirements, masking requirements, retention, and access group. The MVP validates these controls before data extraction and records relevant security metadata in the manifest. It does not implement encryption or masking yet.

## Requirements Templates

Excel templates for capturing source-object requirements are available in `templates/`:

- `ingestion_source_requirements_template.xlsx` for blank requirements capture.
- `sample_csv_customers_requirements.xlsx` as a completed CSV example matching the MVP sample config.
- `filled_source_type_examples.xlsx` with completed file/CSV, database, and API examples.

The workbooks use stable `field_path` columns so a future generator can map rows to `configs/sources/*.yaml` and `configs/storage.yaml`. Regenerate them with:

```bash
python tools/generate_requirement_templates.py
```

The revised templates include a `Schema_Policy` sheet with three capture modes:

- `explicit`: list every column in `Schema_Columns`.
- `infer`: ingest every source column or field without listing each one.
- `hybrid`: ingest every source column or field, but list selected columns for type, key, watermark, or masking overrides.

## Metadata Management App

The local metadata management app provides a friendly UI and API for creating, saving, editing, previewing, and exporting source definitions.

Run it with:

```bash
uvicorn metadata_api.app:app --reload --host 127.0.0.1 --port 8000
```

Then open:

```text
http://127.0.0.1:8000
```

The first version stores source definitions in SQLite at `data/metadata/metadata.db`, supports dynamic column entry, and exports YAML to `configs/sources/<object_id>.yaml`. CSV/file source definitions are executable by the current ingestion framework. Database and API definitions can be captured for future connector milestones.

Completed Excel requirements workbooks can also be converted directly to source YAML:

```bash
python tools/import_source_requirements.py \
  --input /path/to/completed_requirements.xlsx \
  --output configs/sources/<object_id>.yaml
```

For bulk imports, point the importer at a configurable folder:

```bash
python tools/import_source_requirements.py \
  --input-folder /path/to/completed_requirements_folder \
  --output-dir configs/sources \
  --metadata-db data/metadata/metadata.db
```

Use `--dry-run` to validate every workbook and sheet without writing YAML or updating SQLite:

```bash
python tools/import_source_requirements.py \
  --input-folder /path/to/completed_requirements_folder \
  --output-dir configs/sources \
  --metadata-db data/metadata/metadata.db \
  --dry-run
```

Batch mode skips Excel temp files such as `~$example.xlsx`, processes every non-`Validation_Lists` sheet in each workbook, continues after individual failures, and writes a JSON report under `data/metadata/import_reports/`.

The importer validates the generated metadata against the framework config model. It does not read passwords or other secrets from the workbook.
