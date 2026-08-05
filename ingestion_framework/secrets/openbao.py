from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


@dataclass(frozen=True)
class OpenBaoSecretReference:
    """Reference to a single field within an OpenBao secret payload."""

    path: str
    field: str


def is_openbao_reference(value: str | None) -> bool:
    if value is None:
        return False
    stripped = str(value).strip()
    return stripped.startswith("openbao:") or stripped.startswith("openbao://")


def parse_openbao_reference(reference: str) -> OpenBaoSecretReference:
    """Parse an OpenBao field reference such as secret/data/app/minio#access_key."""
    value = reference.strip()
    if value.startswith("openbao://"):
        value = value.removeprefix("openbao://")
    elif value.startswith("openbao:"):
        value = value.removeprefix("openbao:")
    else:
        raise ValueError(f"Not an OpenBao secret reference: {reference}")

    path, separator, field = value.partition("#")
    path = path.strip().strip("/")
    field = field.strip()
    if not path:
        raise ValueError("OpenBao secret reference path cannot be empty")
    if not separator or not field:
        raise ValueError(
            "OpenBao secret reference must include a field name, for example "
            "openbao:secret/data/ingestion-framework/minio#access_key"
        )
    return OpenBaoSecretReference(path=path, field=field)


class OpenBaoClient:
    """Minimal OpenBao HTTP client for reading KV secrets."""

    def __init__(self, addr: str | None = None, token: str | None = None, session=None) -> None:
        self.addr = (addr or _openbao_addr()).rstrip("/")
        self.token = token or _openbao_token()
        self.session = session or requests.Session()

    def read_field(self, reference: str) -> str:
        parsed = parse_openbao_reference(reference)
        payload = self.read_secret(parsed.path)
        secret_data = _unwrap_kv_payload(payload)
        if parsed.field not in secret_data:
            raise KeyError(f"OpenBao secret field is missing: {parsed.path}#{parsed.field}")
        value = secret_data[parsed.field]
        if value is None:
            raise ValueError(f"OpenBao secret field is null: {parsed.path}#{parsed.field}")
        return str(value)

    def read_secret(self, path: str) -> dict[str, Any]:
        url = f"{self.addr}/v1/{quote(path.strip('/'), safe='/')}"
        response = self.session.get(url, headers={"X-Vault-Token": self.token}, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError(f"Unexpected OpenBao response for path: {path}")
        return payload


def read_openbao_field(reference: str) -> str:
    return OpenBaoClient().read_field(reference)


def _openbao_addr() -> str:
    for name in ("OPENBAO_ADDR", "BAO_ADDR", "VAULT_ADDR"):
        value = os.getenv(name)
        if value:
            return value
    raise RuntimeError(
        "OpenBao address is not configured. Set OPENBAO_ADDR, BAO_ADDR, or VAULT_ADDR."
    )


def _openbao_token() -> str:
    for name in ("OPENBAO_TOKEN_FILE", "BAO_TOKEN_FILE", "VAULT_TOKEN_FILE"):
        path = os.getenv(name)
        if path:
            token = Path(path).read_text(encoding="utf-8").strip()
            if token:
                return token
            raise RuntimeError(f"OpenBao token file is empty: {path}")

    for name in ("OPENBAO_TOKEN", "BAO_TOKEN", "VAULT_TOKEN"):
        value = os.getenv(name)
        if value:
            return value
    raise RuntimeError(
        "OpenBao token is not configured. Prefer OPENBAO_TOKEN_FILE; "
        "OPENBAO_TOKEN, BAO_TOKEN, and VAULT_TOKEN are also supported."
    )


def _unwrap_kv_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("OpenBao response does not contain a data object")

    nested = data.get("data")
    if isinstance(nested, dict):
        return nested
    return data
