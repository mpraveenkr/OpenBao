from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ingestion_framework.audit.manifest import ManifestWriter
from ingestion_framework.connectors.database import (
    DatabaseExtractor,
    get_max_watermark_value,
)
from ingestion_framework.normalizers.types import TypeMapper
from ingestion_framework.processors.base import ProcessorContext, ProcessorResult
from ingestion_framework.processors.csv import add_ingestion_metadata
from ingestion_framework.quality import enforce_dq_checks, enforce_dq_counts
from ingestion_framework.writers.format.parquet import ParquetWriter, StreamingParquetWriter
from ingestion_framework.writers.storage.factory import build_storage_writer


class DatabaseProcessor:
    """Run the Bronze ingestion workflow for database source objects."""

    def __init__(self, extractor: DatabaseExtractor | None = None, engine_factory: Any | None = None) -> None:
        self.extractor = extractor or DatabaseExtractor(engine_factory=engine_factory)

    def run(self, context: ProcessorContext) -> ProcessorResult:
        source = context.source
        if getattr(source.extraction, "fetch_size", None):
            return self._run_streaming(context)

        extract_result = self.extractor.extract(
            source,
            base_dir=context.base_dir,
            watermark_store=context.watermark_store,
        )
        rows_extracted = len(extract_result.frame)
        enforce_dq_checks(source, extract_result.frame)

        typed = TypeMapper().apply(extract_result.frame, extract_result.runtime_schema)
        watermark_value = get_max_watermark_value(typed, source)
        ingested = add_ingestion_metadata(typed, source, context.run_id)
        rows_written = len(ingested)

        target_key = build_target_key(source, context.run_id)
        storage_writer = build_storage_writer(context.storage, context.base_dir)
        parquet_writer = ParquetWriter()

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_parquet = Path(temp_dir) / "part-00001.parquet"
            parquet_writer.write(ingested, temp_parquet, source.target.compression)
            final_parquet_path = storage_writer.write_file(temp_parquet, target_key)

        manifest_key = str(Path(target_key).parent / "_manifest.json")
        manifest = ManifestWriter().build(
            source=source,
            storage=context.storage,
            run_id=context.run_id,
            rows_extracted=rows_extracted,
            rows_written=rows_written,
            target_files=[str(final_parquet_path)],
        )
        manifest["schema_mode"] = source.schema_policy.get("mode")
        manifest["column_discovery"] = source.schema_policy.get("column_discovery")
        manifest["type_discovery"] = source.schema_policy.get("type_discovery")
        manifest["runtime_schema_columns"] = len(extract_result.runtime_schema.columns)
        manifest_path = storage_writer.write_bytes(
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            manifest_key,
        )

        return ProcessorResult(
            rows_extracted=rows_extracted,
            rows_written=rows_written,
            target_path=str(final_parquet_path),
            manifest_path=str(manifest_path),
            watermark_value=watermark_value,
        )

    def _run_streaming(self, context: ProcessorContext) -> ProcessorResult:
        source = context.source
        extract_result = self.extractor.extract_chunks(
            source,
            base_dir=context.base_dir,
            watermark_store=context.watermark_store,
        )
        target_key = build_target_key(source, context.run_id)
        storage_writer = build_storage_writer(context.storage, context.base_dir)

        rows_extracted = 0
        rows_written = 0
        watermark_value: str | None = None

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_parquet = Path(temp_dir) / "part-00001.parquet"
            with StreamingParquetWriter(temp_parquet, source.target.compression) as parquet_writer:
                wrote_any_chunk = False
                for chunk in extract_result.chunks:
                    rows_extracted += len(chunk)
                    typed = TypeMapper().apply(chunk, extract_result.runtime_schema)
                    watermark_value = max_watermark_value(
                        watermark_value,
                        get_max_watermark_value(typed, source),
                        source,
                    )
                    ingested = add_ingestion_metadata(typed, source, context.run_id)
                    rows_written += len(ingested)
                    parquet_writer.write_chunk(ingested)
                    wrote_any_chunk = True

                enforce_dq_counts(source, rows_extracted)

                if not wrote_any_chunk:
                    empty_frame = TypeMapper().apply(
                        empty_runtime_frame(extract_result.runtime_schema),
                        extract_result.runtime_schema,
                    )
                    parquet_writer.write_chunk(
                        add_ingestion_metadata(empty_frame, source, context.run_id)
                    )

            final_parquet_path = storage_writer.write_file(temp_parquet, target_key)

        manifest_key = str(Path(target_key).parent / "_manifest.json")
        manifest = ManifestWriter().build(
            source=source,
            storage=context.storage,
            run_id=context.run_id,
            rows_extracted=rows_extracted,
            rows_written=rows_written,
            target_files=[str(final_parquet_path)],
        )
        manifest["schema_mode"] = source.schema_policy.get("mode")
        manifest["column_discovery"] = source.schema_policy.get("column_discovery")
        manifest["type_discovery"] = source.schema_policy.get("type_discovery")
        manifest["runtime_schema_columns"] = len(extract_result.runtime_schema.columns)
        manifest["write_mode"] = "streaming_chunks"
        manifest_path = storage_writer.write_bytes(
            json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8"),
            manifest_key,
        )

        return ProcessorResult(
            rows_extracted=rows_extracted,
            rows_written=rows_written,
            target_path=str(final_parquet_path),
            manifest_path=str(manifest_path),
            watermark_value=watermark_value,
        )


def empty_runtime_frame(runtime_schema) -> Any:
    import pandas as pd

    return pd.DataFrame(columns=list(runtime_schema.columns))


def max_watermark_value(current: str | None, candidate: str | None, source: Any) -> str | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    watermark = getattr(source.extraction, "watermark", None) or {}
    watermark_type = str(
        watermark.get("value_type") if isinstance(watermark, dict) else ""
    ) or str(getattr(source.extraction, "watermark_type", "") or "")
    if watermark_type.lower() in {"integer", "bigint"}:
        return str(max(int(current), int(candidate)))
    if watermark_type.lower() in {"decimal", "float"}:
        return str(max(float(current), float(candidate)))
    return max(current, candidate)


def build_target_key(source: Any, run_id: str) -> str:
    now = datetime.now(timezone.utc)
    return str(
        Path(source.target.zone)
        / "source_type=database"
        / f"source_system={source.source_system}"
        / f"object={source.object_name}"
        / f"ingest_year={now:%Y}"
        / f"ingest_month={now:%m}"
        / f"ingest_day={now:%d}"
        / f"run_id={run_id}"
        / "part-00001.parquet"
    )
