from __future__ import annotations

import os

from ingestion_framework.secrets.openbao import is_openbao_reference, read_openbao_field


def is_secret_reference(value: str | None) -> bool:
    return is_openbao_reference(value)


def resolve_secret_reference(reference: str) -> str:
    if not is_secret_reference(reference):
        raise ValueError(f"Unsupported secret reference: {reference}")
    return read_openbao_field(reference)


def resolve_value(value: str | None) -> str | None:
    """Resolve an inline value if it is an OpenBao reference."""
    if value is None:
        return None
    stripped = str(value).strip()
    if is_secret_reference(stripped):
        return resolve_secret_reference(stripped)
    return stripped


def resolve_env_or_secret(name_or_reference: str | None, *, label: str) -> str:
    """Resolve either an environment-variable name or an inline OpenBao reference.

    Runtime settings can still point at environment variable names when the value
    is non-secret or when deployment injects only an OpenBao reference into env.
    If the env var value contains an OpenBao reference, that is resolved too.
    """
    if name_or_reference is None or str(name_or_reference).strip() == "":
        raise ValueError(f"{label} is required")

    candidate = str(name_or_reference).strip()
    if is_secret_reference(candidate):
        value = resolve_secret_reference(candidate)
    else:
        env_value = os.getenv(candidate)
        if not env_value:
            raise RuntimeError(f"Required environment variable is not set: {candidate}")
        value = resolve_value(env_value)

    if value is None or str(value).strip() == "":
        raise RuntimeError(f"Resolved secret value is empty: {label}")
    return str(value)
