from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from ingestion_framework.audit.manifest import ManifestWriter
from ingestion_framework.connectors.file_csv import CsvFileExtractor
from ingestion_framework.normalizers.columns import ColumnNormalizer
from ingestion_framework.normalizers.types import TypeMapper
from ingestion_framework.processors.base import ProcessorContext, ProcessorResult
from ingestion_framework.quality import enforce_dq_checks
from ingestion_framework.writers.format.parquet import ParquetWriter
from ingestion_framework.writers.storage.factory import build_storage_writer


class CsvProcessor:
    def run(self, context: ProcessorContext) -> ProcessorResult:
        source = context.source
        storage = context.storage
        run_id = context.run_id

        extracted = CsvFileExtractor(source.extraction, context.base_dir).extract()
        rows_extracted = len(extracted)
        enforce_dq_checks(source, extracted)

        extracted.columns = ColumnNormalizer().normalize(list(extracted.columns))
        typed = TypeMapper().apply(extracted, source.schema)
        ingested = add_ingestion_metadata(typed, source, run_id)
        rows_written = len(ingested)

        target_key = build_target_key(source, run_id)
        storage_writer = build_storage_writer(storage, context.base_dir)
        parquet_writer = ParquetWriter()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_parquet = Path(temp_dir) / "part-00001.parquet"
            parquet_writer.write(ingested, temp_parquet, source.target.compression)
            final_parquet_path = storage_writer.write_file(temp_parquet, target_key)

        manifest_key = str(Path(target_key).parent / "_manifest.json")
        manifest_writer = ManifestWriter()
        manifest = manifest_writer.build(
            source=source,
            storage=storage,
            run_id=run_id,
            rows_extracted=rows_extracted,
            rows_written=rows_written,
            target_files=[str(final_parquet_path)],
        )
        manifest_path = storage_writer.write_bytes(
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            manifest_key,
        )

        return ProcessorResult(
            rows_extracted=rows_extracted,
            rows_written=rows_written,
            target_path=str(final_parquet_path),
            manifest_path=str(manifest_path),
        )


def add_ingestion_metadata(frame, source, run_id: str):
    now = datetime.now(timezone.utc).isoformat()
    result = frame.copy()
    result["_ingest_run_id"] = run_id
    result["_ingest_timestamp_utc"] = now
    result["_source_system"] = source.source_system
    result["_source_type"] = source.source_type
    result["_source_object"] = source.object_name
    result["_load_strategy"] = source.load_strategy
    return result


def build_target_key(source, run_id: str) -> str:
    now = datetime.now(timezone.utc)
    return str(
        Path(source.target.zone)
        / "source_type=file"
        / f"source_system={source.source_system}"
        / f"object={source.object_name}"
        / f"ingest_year={now:%Y}"
        / f"ingest_month={now:%m}"
        / f"ingest_day={now:%d}"
        / f"run_id={run_id}"
        / "part-00001.parquet"
    )
