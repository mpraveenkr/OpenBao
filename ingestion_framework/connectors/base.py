from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class BaseExtractor(ABC):
    @abstractmethod
    def extract(self) -> pd.DataFrame:
        """Extract source data into a DataFrame."""
