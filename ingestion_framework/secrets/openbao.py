from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests

DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 0.5
_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})


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

    def __init__(
        self,
        addr: str | None = None,
        token: str | None = None,
        session=None,
        verify: bool | str | None = None,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS,
    ) -> None:
        self.addr = (addr or _openbao_addr()).rstrip("/")
        self.token = token or _openbao_token()
        self.session = session or requests.Session()
        self.verify = _openbao_verify() if verify is None else verify
        self.max_attempts = max(1, max_attempts)
        self.retry_backoff_seconds = retry_backoff_seconds
        self._cache: dict[str, dict[str, Any]] = {}

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
        """Read a secret payload, reusing an already-fetched path within this client.

        Configs routinely reference several fields of one secret, such as an
        access key and a secret key, so caching avoids repeated round trips.
        """
        normalized = path.strip("/")
        if normalized in self._cache:
            return self._cache[normalized]

        payload = self._request(normalized)
        self._cache[normalized] = payload
        return payload

    def clear_cache(self) -> None:
        self._cache.clear()

    def _request(self, path: str) -> dict[str, Any]:
        url = f"{self.addr}/v1/{quote(path, safe='/')}"
        last_error: Exception | None = None

        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.session.get(
                    url,
                    headers={"X-Vault-Token": self.token},
                    timeout=30,
                    verify=self.verify,
                )
                # Retry only transient server-side failures. A 403 or 404 is a
                # configuration problem and will not improve by trying again.
                if _is_retryable_status(response) and attempt < self.max_attempts:
                    last_error = requests.HTTPError(
                        f"OpenBao returned {response.status_code} for {path}"
                    )
                    self._sleep_before_retry(attempt)
                    continue
                response.raise_for_status()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    break
                self._sleep_before_retry(attempt)
                continue

            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"Unexpected OpenBao response for path: {path}")
            return payload

        raise RuntimeError(
            f"Could not read OpenBao secret after {self.max_attempts} attempts: {path}"
        ) from last_error

    def _sleep_before_retry(self, attempt: int) -> None:
        if self.retry_backoff_seconds > 0:
            time.sleep(self.retry_backoff_seconds * attempt)


_CLIENT_CACHE: dict[tuple[str, str], OpenBaoClient] = {}


def read_openbao_field(reference: str) -> str:
    return _shared_client().read_field(reference)


def _shared_client() -> OpenBaoClient:
    """Return a per-process client so its secret cache spans a whole run.

    Keying on the address and token means a rotated token or a reconfigured
    address transparently produces a fresh client instead of reusing stale
    credentials or cached secrets.
    """
    key = (_openbao_addr().rstrip("/"), _openbao_token())
    client = _CLIENT_CACHE.get(key)
    if client is None:
        client = OpenBaoClient(addr=key[0], token=key[1])
        _CLIENT_CACHE.clear()
        _CLIENT_CACHE[key] = client
    return client


def reset_openbao_clients() -> None:
    """Drop cached clients and their cached secrets."""
    _CLIENT_CACHE.clear()


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


def _openbao_verify() -> bool | str:
    """Resolve TLS verification for OpenBao requests.

    Returns a CA bundle path when one is configured, otherwise a bool. Skipping
    verification has to be requested explicitly so an HTTPS deployment cannot end
    up unverified by accident.
    """
    for name in ("OPENBAO_SKIP_VERIFY", "BAO_SKIP_VERIFY", "VAULT_SKIP_VERIFY"):
        value = os.getenv(name)
        if value and value.strip().lower() in {"1", "true", "yes", "on"}:
            return False

    for name in ("OPENBAO_CACERT", "BAO_CACERT", "VAULT_CACERT"):
        value = os.getenv(name)
        if value:
            path = Path(value)
            if not path.exists():
                raise RuntimeError(f"OpenBao CA certificate file does not exist: {value}")
            return str(path)

    return True


def _is_retryable_status(response: Any) -> bool:
    status_code = getattr(response, "status_code", None)
    return status_code in _RETRYABLE_STATUS_CODES


def _unwrap_kv_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("OpenBao response does not contain a data object")

    nested = data.get("data")
    if isinstance(nested, dict):
        return nested
    return data
