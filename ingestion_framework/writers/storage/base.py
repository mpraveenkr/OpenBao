from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Union


StorageWriteResult = Union[Path, str]


class BaseStorageWriter(ABC):
    @abstractmethod
    def write_file(self, source_file: str | Path, target_key: str) -> StorageWriteResult:
        """Write a local file to target storage and return the final path."""

    @abstractmethod
    def write_bytes(self, content: bytes, target_key: str) -> StorageWriteResult:
        """Write bytes to target storage and return the final path/URI."""
