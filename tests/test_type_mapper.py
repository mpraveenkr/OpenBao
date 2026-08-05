from __future__ import annotations

import pandas as pd
import pytest

from ingestion_framework.config.validator import ColumnConfig, SchemaConfig
from ingestion_framework.normalizers.types import TypeMapper


def test_type_mapper_converts_supported_types_and_adds_nullable_missing_columns():
    frame = pd.DataFrame(
        {
            "customer_id": ["1001"],
            "created_date": ["2026-05-01"],
            "updated_timestamp": ["2026-05-14T10:30:00Z"],
        }
    )
    schema = SchemaConfig(
        columns={
            "customer_id": ColumnConfig(type="string", nullable=False),
            "customer_name": ColumnConfig(type="string", nullable=True),
            "created_date": ColumnConfig(type="date", nullable=True),
            "updated_timestamp": ColumnConfig(type="timestamp", nullable=True),
        }
    )

    result = TypeMapper().apply(frame, schema)

    assert "customer_name" in result.columns
    assert str(result["customer_id"].dtype) == "string"
    assert str(result["updated_timestamp"].dtype) == "datetime64[ns, UTC]"


def test_type_mapper_raises_for_missing_non_nullable_column():
    schema = SchemaConfig(columns={"customer_id": ColumnConfig(type="string", nullable=False)})

    with pytest.raises(ValueError, match="non-nullable column"):
        TypeMapper().apply(pd.DataFrame({}), schema)
