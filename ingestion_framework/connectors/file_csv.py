from __future__ import annotations

from pathlib import Path

import pandas as pd

from ingestion_framework.config.validator import ExtractionConfig
from ingestion_framework.connectors.base import BaseExtractor


class CsvFileExtractor(BaseExtractor):
    def __init__(self, extraction: ExtractionConfig, base_dir: str | Path | None = None) -> None:
        self.extraction = extraction
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()

    def extract(self) -> pd.DataFrame:
        source_path = self._resolve_path(self.extraction.path)
        if not source_path.exists():
            raise FileNotFoundError(f"CSV source file not found: {source_path}")

        header = 0 if self.extraction.header else None
        frame = pd.read_csv(
            source_path,
            delimiter=self.extraction.delimiter,
            header=header,
            encoding=self.extraction.encoding,
        )
        stat = source_path.stat()
        modified = pd.Timestamp.fromtimestamp(stat.st_mtime, tz="UTC").isoformat()
        frame["_source_file_path"] = str(source_path)
        frame["_source_file_name"] = source_path.name
        frame["_source_file_size_bytes"] = stat.st_size
        frame["_source_file_modified_timestamp"] = modified
        return frame

    def _resolve_path(self, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.base_dir / candidate
