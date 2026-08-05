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

Secrets are not stored in YAML. Local development uses SQLite for audit/watermark state and local filesystem storage.

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

## Future Phases

Phase 2: database extractor.

Phase 3: API extractor.

Phase 4: S3 and Nutanix Objects writer through S3-compatible APIs.

Phase 5: Azure Data Lake Storage Gen2 writer.

Phase 6: Airflow wrapper.

Phase 7: Azure Data Factory/container execution.
