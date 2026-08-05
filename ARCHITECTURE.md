# Architecture

## Target Architecture

The framework is metadata-driven. Each source object is onboarded primarily through YAML containing object identity, source metadata, extraction rules, schema rules, target rules, audit rules, and security controls.

The long-term flow is:

1. Load and validate source object config.
2. Extract from a configured connector.
3. Normalize column names.
4. Apply schema and type mapping.
5. Add ingestion metadata.
6. Write immutable bronze output under a unique `run_id`.
7. Create a manifest next to the data files.
8. Commit audit status and watermarks only after successful target write.

Secrets are not stored in YAML. Configs hold OpenBao references, which the
framework resolves at runtime. Local development uses SQLite for audit/watermark
state and local filesystem storage.

## Current MVP

Implemented in this milestone:

- CSV file extraction.
- YAML source and storage config loading.
- Pydantic config validation.
- Column normalization.
- Basic pandas type mapping.
- Local Parquet writes with pyarrow.
- Local filesystem storage writer.
- `_manifest.json` creation.
- SQLite audit logger.
- SQLite watermark store placeholder.
- CLI command for one source object.
- Pytest coverage for config, normalization, type mapping, CSV extraction, security validation, and full local ingestion.

## Delivered Since The MVP

- Database extractor, including SQL Server metadata-driven schema discovery.
- API extractor with pagination, parameter sets, and JSON flattening.
- S3-compatible writer for MinIO and Nutanix Objects.
- Azure Data Lake Storage Gen2 writer, authenticating with an Entra ID service principal or an account key.
- Postgres-backed audit and watermark stores.
- Airflow DAG generator and a single-node Airflow deployment.
- OpenBao-backed secret resolution, with the server deployed and provisioned as part of that stack.

## Future Phases

- Encryption and masking enforcement, which the security metadata currently records but does not apply.
- Azure Data Factory or container-based execution as an alternative to Airflow.
- Moving platform bootstrap secrets for Postgres, MinIO, and Airflow into OpenBao.
- TLS on the OpenBao listener, with AppRole replacing the static periodic token.
