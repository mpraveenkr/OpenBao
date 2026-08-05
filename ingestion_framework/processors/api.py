from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from ingestion_framework.audit.manifest import ManifestWriter
from ingestion_framework.connectors.api import ApiExtractor
from ingestion_framework.normalizers.types import TypeMapper
from ingestion_framework.processors.base import ProcessorContext, ProcessorResult
from ingestion_framework.processors.csv import add_ingestion_metadata
from ingestion_framework.quality import enforce_dq_checks
from ingestion_framework.writers.format.parquet import ParquetWriter
from ingestion_framework.writers.storage.factory import build_storage_writer


class ApiProcessor:
    """Run the Bronze ingestion workflow for API source objects."""

    def __init__(self, extractor_factory: Any | None = None, session: Any | None = None) -> None:
        self.extractor_factory = extractor_factory or ApiExtractor
        self.session = session

    def run(self, context: ProcessorContext) -> ProcessorResult:
        source = context.source
        extracted = self.extractor_factory(
            source,
            base_dir=context.base_dir,
            session=self.session,
        ).extract()
        rows_extracted = len(extracted)
        enforce_dq_checks(source, extracted)

        extracted = align_columns_to_schema(extracted, source)
        typed = TypeMapper().apply(extracted, source.schema)
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


def align_columns_to_schema(frame: pd.DataFrame, source: Any) -> pd.DataFrame:
    result = frame.copy()
    for column_name in source.schema.columns:
        if column_name not in result.columns:
            result[column_name] = pd.NA
    return result


def build_target_key(source: Any, run_id: str) -> str:
    now = datetime.now(timezone.utc)
    return str(
        Path(source.target.zone)
        / "source_type=api"
        / f"source_system={source.source_system}"
        / f"object={source.object_name}"
        / f"ingest_year={now:%Y}"
        / f"ingest_month={now:%m}"
        / f"ingest_day={now:%d}"
        / f"run_id={run_id}"
        / "part-00001.parquet"
    )
