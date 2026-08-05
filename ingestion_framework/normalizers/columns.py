from __future__ import annotations

import re


class ColumnNormalizer:
    def normalize(self, columns: list[str]) -> list[str]:
        seen: dict[str, int] = {}
        normalized: list[str] = []
        for column in columns:
            base = self.normalize_one(column)
            count = seen.get(base, 0) + 1
            seen[base] = count
            normalized.append(base if count == 1 else f"{base}_{count}")
        return normalized

    @staticmethod
    def normalize_one(column: object) -> str:
        value = str(column).strip().lower()
        value = re.sub(r"[\s-]+", "_", value)
        value = re.sub(r"[^a-z0-9_]", "", value)
        value = re.sub(r"_+", "_", value).strip("_")
        return value or "unnamed_column"
