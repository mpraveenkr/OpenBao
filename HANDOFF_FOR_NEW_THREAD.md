# Ingestion Framework Handoff

Use this file to start a fresh Codex thread without carrying the full prior conversation.

## Workspace

Project root:

```text
/Users/badari/Downloads/ingestion-framework
```

Use this as the working directory in the new thread.

## Current Goal

Build a production-style, metadata-driven Python ingestion framework for Bronze-layer ingestion.

The framework is YAML-driven and supports onboarding new source objects primarily through metadata templates/YAML instead of hand-written pipelines.

## Major Components Built

### Core Framework

Implemented:

- CLI entrypoint: `ingest-object`
- Source YAML loading and validation
- Storage YAML loading and validation
- Runner orchestration
- Audit logging
- Watermark store
- Manifest writer
- Column normalization
- Type mapping
- Security policy validation
- Local and S3-compatible/MinIO storage writers
- Parquet writer

Important paths:

```text
ingestion_framework/cli.py
ingestion_framework/core/runner.py
ingestion_framework/config/loader.py
ingestion_framework/config/validator.py
ingestion_framework/audit/audit_logger.py
ingestion_framework/audit/watermark_store.py
ingestion_framework/audit/manifest.py
ingestion_framework/storage/local.py
ingestion_framework/storage/s3_compatible.py
ingestion_framework/storage/factory.py
ingestion_framework/storage/parquet.py
ingestion_framework/normalizers/columns.py
ingestion_framework/normalizers/types.py
```

### CSV Processor

Implemented:

- CSV extraction
- Column normalization
- Type mapping
- Ingestion metadata columns
- Parquet write
- Manifest
- Audit

Important paths:

```text
ingestion_framework/connectors/file_csv.py
ingestion_framework/processors/csv.py
configs/sources/sample_csv_customers.yaml
data/input/customers.csv
```

### API Processor

Implemented and aligned to latest tabbed API workbook template design.

Supports:

- GET APIs
- `api_key_header` auth using env vars
- No-auth APIs
- Runtime parameters
- Current-date offsets
- Path/query placeholder substitution
- PJM `offset_limit` pagination
- MISO `page_number` pagination
- Parameter-set iteration from station CSV files
- Open-Meteo timeseries array flattening
- Metadata field propagation onto hourly rows
- Daily date fallback for weather rows
- CamelCase/nested JSON flattening into snake_case
- Query parameter type coercion
- Basic retries
- Rate-limit delay support
- Parquet/manifest/audit path through existing framework

Important paths:

```text
ingestion_framework/processors/api.py
metadata_api/tabbed_api_importer.py
tools/import_api_templates.py
configs/sources/api_generated/
data/input/miso_stations.csv
data/input/pjm_stations.csv
```

Generated API YAML files:

```text
configs/sources/api_generated/miso_forecast.yaml
configs/sources/api_generated/miso_realtime.yaml
configs/sources/api_generated/pjm_load_forecast.yaml
configs/sources/api_generated/pjm_hrl_load_metered.yaml
configs/sources/api_generated/weather_archive.yaml
configs/sources/api_generated/weather_forecast.yaml
```

API templates source folder:

```text
/Users/badari/Downloads/api_templates
```

Regenerate API YAML:

```bash
.venv/bin/python tools/import_api_templates.py \
  --input-folder /Users/badari/Downloads/api_templates \
  --output-dir configs/sources/api_generated \
  --report-dir data/metadata/import_reports
```

Live Open-Meteo smoke test was performed with one station and one day. It succeeded and wrote 24 hourly rows.

### Database Processor

Implemented.

Supports:

- Full load when no watermark exists
- Incremental validation failure when watermark is missing
- Incremental query using `:last_watermark`
- Watermark lookup from watermark store
- Watermark commit only after successful target write and audit completion
- Compact YAML `infer` and `hybrid` modes
- Database metadata-driven runtime schema discovery
- Database-specific type mapping
- YAML column overrides applied on top of discovered metadata
- Parquet/manifest/audit path through existing framework

Database metadata discovery currently factored for:

- SQLite
- SQL Server
- PostgreSQL

Important paths:

```text
ingestion_framework/processors/database.py
tests/test_database_processor.py
```

Important design:

- `schema_policy.mode: infer`: discover all columns/types from source metadata.
- `schema_policy.mode: hybrid`: discover all columns/types, then apply YAML column overrides.
- `Column_Overrides` should only include primary keys, watermarks, masks/PII/BCSI, special type handling, or renames.

### Database YAML Generation

Compact database templates were generated from old database templates.

Old database templates source folder:

```text
/Users/badari/Downloads/database_templates
```

Generated compact Excel templates:

```text
templates/generated_compact_database_templates/
```

Generated compact database YAML:

```text
configs/sources/database_compact_generated/
```

Counts:

```text
database YAML files: 2129
full loads: 2115
incremental loads: 14
infer schemas: 2017
hybrid schemas: 112
```

Relevant tools:

```text
tools/generate_compact_database_workbooks.py
tools/import_normalized_database_workbook.py
metadata_api/normalized_database_importer.py
```

Regenerate compact database Excel templates:

```bash
.venv/bin/python tools/generate_compact_database_workbooks.py \
  --input-folder /Users/badari/Downloads/database_templates \
  --output-dir templates/generated_compact_database_templates
```

Regenerate database YAML from one compact workbook:

```bash
.venv/bin/python tools/import_normalized_database_workbook.py \
  --input templates/generated_compact_database_templates/MV90_Master_CMMASTST_SQL_Server_compact.xlsx \
  --output-dir configs/sources/database_compact_generated
```

To regenerate all database YAMLs, loop over:

```text
templates/generated_compact_database_templates/*.xlsx
```

## Metadata Management App

A simple React/FastAPI metadata manager exists.

Important paths:

```text
metadata_api/app.py
metadata_api/repository.py
metadata_api/models.py
metadata_api/yaml_generator.py
metadata_api/excel_importer.py
metadata_ui/index.html
metadata_ui/assets/app.jsx
metadata_ui/assets/styles.css
data/metadata/metadata.db
```

The app was previously launched locally at:

```text
http://127.0.0.1:8000/
```

## Storage

Storage configs:

```text
configs/storage.yaml
configs/storage_minio.yaml
```

Local writer is built.

S3-compatible writer is built and intended to support MinIO/Nutanix Objects/S3-compatible endpoints.

MinIO runtime credentials should be stored in OpenBao. `configs/storage_minio.yaml` now uses:

```text
endpoint_url: http://minio:9000
access_key_ref: openbao:secret/data/ingestion-framework/minio#access_key
secret_key_ref: openbao:secret/data/ingestion-framework/minio#secret_key
```

The runtime needs `OPENBAO_ADDR` and preferably `OPENBAO_TOKEN_FILE`.

The single-node Compose stack now runs OpenBao itself and provisions it on
startup, including the policy, the Airflow token, and the MinIO and audit
secrets. See `deploy/single-node-airflow/README.md`.

## Single-Node Airflow Deployment

Deployment folder:

```text
deploy/single-node-airflow/
```

Important files:

```text
deploy/single-node-airflow/docker-compose.yml
deploy/single-node-airflow/install_platform.py
deploy/single-node-airflow/Dockerfile.airflow
deploy/single-node-airflow/requirements-airflow.txt
deploy/single-node-airflow/dags/ingestion_smoke_test.py
deploy/single-node-airflow/generated/minio-bootstrap.sh
deploy/single-node-airflow/generated/airflow-bootstrap.sh
```

The user's single-node Airflow environment has:

- Dockerized Airflow
- MinIO
- Postgres
- Buckets created
- OpenBao-backed runtime secret references for ingestion credentials

Runtime env vars mentioned:

```text
OPENBAO_ADDR=http://openbao:8200
OPENBAO_TOKEN_FILE=/run/secrets/openbao_token
INGESTION_AUDIT_DB_URL=openbao:secret/data/ingestion-framework/audit#url
```

## Tests

Current full test suite status at last run:

```text
33 passed
```

Run tests:

```bash
.venv/bin/python -m pytest
```

## Current Important Generated Folders

```text
configs/sources/api_generated/
configs/sources/database_compact_generated/
templates/generated_compact_database_templates/
data/input/miso_stations.csv
data/input/pjm_stations.csv
```

## Current Readiness

Ready:

- CSV ingestion
- API ingestion
- Database ingestion
- Compact database YAML design
- Database metadata type discovery
- API tabbed template import
- Database compact workbook import
- Local writer
- MinIO/S3-compatible writer
- Manifest, audit, watermark basics

Not yet built:

- Airflow DAG generator
- Airflow DAG deployment automation for generated YAMLs
- Postgres audit/watermark backend
- ADLS Gen2 writer
- Full SQL Server live smoke test in single-node Airflow
- Full MinIO live write smoke test in single-node Airflow

## Recommended Next Milestone

Build the Airflow DAG Generator.

Suggested target:

```text
tools/generate_airflow_dags.py
deploy/single-node-airflow/dags/generated/
```

First implementation should:

- Read source YAML files from selected folders.
- Generate one DAG per YAML object by default.
- Use manual schedule unless orchestration metadata exists.
- Run the existing CLI:

```bash
ingest-object run-object \
  --config <source-yaml> \
  --storage <storage-yaml> \
  --audit-db <audit-db>
```

- Allow filtering by source type/source system/object id.
- Avoid generating all 2,129 database DAGs by default unless explicitly requested.

Recommended default subset:

```text
configs/sources/api_generated/weather_forecast.yaml
configs/sources/api_generated/weather_archive.yaml
configs/sources/database_compact_generated/itron_mv90_cmmastst_customer_master.yaml
configs/sources/sample_csv_customers.yaml
```

## Suggested First Prompt For New Thread

```text
We are continuing the ingestion-framework project in /Users/badari/Downloads/ingestion-framework.
Please read HANDOFF_FOR_NEW_THREAD.md first.
Then build the Airflow DAG Generator incrementally.
Start with generating DAGs for a small default subset only:
- configs/sources/sample_csv_customers.yaml
- configs/sources/api_generated/weather_forecast.yaml
- configs/sources/api_generated/weather_archive.yaml
- configs/sources/database_compact_generated/itron_mv90_cmmastst_customer_master.yaml

The generator should write DAGs to deploy/single-node-airflow/dags/generated/.
Use the existing CLI command ingest-object run-object.
Run tests after the milestone.
Do not generate DAGs for all 2,129 database YAML files by default.
```
