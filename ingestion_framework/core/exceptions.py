"""Framework-specific exceptions."""


class IngestionFrameworkError(Exception):
    """Base exception for ingestion framework failures."""


class ConfigValidationError(IngestionFrameworkError):
    """Raised when source or storage metadata is invalid."""
