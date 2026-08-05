from __future__ import annotations

import pandas as pd

from ingestion_framework.config.validator import SchemaConfig


class TypeMapper:
    def apply(self, frame: pd.DataFrame, schema: SchemaConfig) -> pd.DataFrame:
        result = frame.copy()
        for column_name, column_config in schema.columns.items():
            if column_name not in result.columns:
                if column_config.nullable:
                    result[column_name] = pd.NA
                else:
                    raise ValueError(f"Required non-nullable column is missing: {column_name}")

            result[column_name] = self._convert(result[column_name], column_config.type)

        return result

    @staticmethod
    def _convert(series: pd.Series, target_type: str) -> pd.Series:
        if target_type == "string":
            return series.astype("string")
        if target_type in {"integer", "bigint"}:
            return pd.to_numeric(series, errors="coerce").astype("Int64")
        if target_type in {"decimal", "float"}:
            return pd.to_numeric(series, errors="coerce")
        if target_type == "boolean":
            return series.astype("boolean")
        if target_type == "date":
            return pd.to_datetime(series, errors="coerce").dt.date
        if target_type == "timestamp":
            return pd.to_datetime(series, errors="coerce", utc=True).astype("datetime64[ns, UTC]")
        raise ValueError(f"Unsupported schema type: {target_type}")
