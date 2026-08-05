from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ingestion_framework.config.validator import SourceObjectConfig, StorageConfig
from ingestion_framework.audit.watermark_store import WatermarkStore


@dataclass(frozen=True)
class ProcessorContext:
    source: SourceObjectConfig
    storage: StorageConfig
    run_id: str
    base_dir: Path
    watermark_store: WatermarkStore | None = None


@dataclass(frozen=True)
class ProcessorResult:
    rows_extracted: int
    rows_written: int
    target_path: str
    manifest_path: str
    watermark_value: str | None = None


class SourceProcessor(Protocol):
    def run(self, context: ProcessorContext) -> ProcessorResult:
        """Execute one configured source object."""
