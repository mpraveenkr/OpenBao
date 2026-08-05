from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


class ParquetWriter:
    def write(self, frame: pd.DataFrame, path: str | Path, compression: str = "snappy") -> Path:
        output_path = Path(path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(output_path, engine="pyarrow", compression=compression, index=False)
        return output_path


class StreamingParquetWriter:
    """Incrementally write pandas chunks as Parquet row groups."""

    def __init__(self, path: str | Path, compression: str = "snappy") -> None:
        self.output_path = Path(path)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.compression = compression
        self._writer: pq.ParquetWriter | None = None

    def write_chunk(self, frame: pd.DataFrame) -> None:
        table = pa.Table.from_pandas(frame, preserve_index=False)
        if self._writer is None:
            self._writer = pq.ParquetWriter(
                self.output_path,
                table.schema,
                compression=self.compression,
            )
        self._writer.write_table(table)

    def close(self) -> Path:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        return self.output_path

    def __enter__(self) -> "StreamingParquetWriter":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
