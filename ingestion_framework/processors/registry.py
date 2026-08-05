from __future__ import annotations

from ingestion_framework.config.validator import SourceObjectConfig
from ingestion_framework.processors.api import ApiProcessor
from ingestion_framework.processors.base import SourceProcessor
from ingestion_framework.processors.csv import CsvProcessor
from ingestion_framework.processors.database import DatabaseProcessor


class ProcessorRegistry:
    def __init__(self) -> None:
        self._api = ApiProcessor()
        self._csv = CsvProcessor()
        self._database = DatabaseProcessor()

    def get(self, source: SourceObjectConfig) -> SourceProcessor:
        if source.source_type == "file" and source.extraction.file_type == "csv":
            return self._csv
        if source.source_type == "api":
            return self._api
        if source.source_type == "database":
            return self._database
        raise NotImplementedError(
            f"No processor registered for source_type={source.source_type!r} "
            f"and file_type={source.extraction.file_type!r}."
        )
