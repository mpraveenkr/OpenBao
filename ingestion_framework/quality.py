from __future__ import annotations

from typing import Any

import pandas as pd


def enforce_dq_checks(source: Any, frame: pd.DataFrame) -> None:
    """Evaluate lightweight DQ checks declared in source YAML metadata."""
    enforce_dq_counts(source, row_count=len(frame))


def enforce_dq_counts(source: Any, row_count: int) -> None:
    """Evaluate DQ checks when only running counters are available."""
    checks = list((source.audit or {}).get("dq_checks") or [])
    for check in checks:
        normalized = str(check).strip().lower()
        if normalized == "row_count_gt_zero":
            if row_count == 0:
                raise ValueError(
                    f"{source.object_id}: DQ check failed: row_count_gt_zero"
                )
        elif normalized:
            raise NotImplementedError(
                f"{source.object_id}: unsupported DQ check: {check}"
            )
