from __future__ import annotations

import pytest

from ingestion_framework.secrets.openbao import OpenBaoClient, parse_openbao_reference
from ingestion_framework.secrets.resolver import resolve_env_or_secret


def test_parse_openbao_reference_requires_path_and_field():
    parsed = parse_openbao_reference(
        "openbao:secret/data/ingestion-framework/minio#access_key"
    )

    assert parsed.path == "secret/data/ingestion-framework/minio"
    assert parsed.field == "access_key"


def test_openbao_client_reads_kv_v2_field():
    session = FakeSession(
        {
            "data": {
                "data": {
                    "access_key": "minio-user",
                    "secret_key": "minio-password",
                },
                "metadata": {"version": 1},
            }
        }
    )

    client = OpenBaoClient(addr="http://openbao:8200", token="token", session=session)

    assert (
        client.read_field("openbao:secret/data/ingestion-framework/minio#access_key")
        == "minio-user"
    )
    assert session.requests == [
        (
            "http://openbao:8200/v1/secret/data/ingestion-framework/minio",
            {"X-Vault-Token": "token"},
            30,
        )
    ]


def test_openbao_client_reads_kv_v1_field():
    session = FakeSession({"data": {"password": "plain-kv1-value"}})

    client = OpenBaoClient(addr="http://openbao:8200", token="token", session=session)

    assert client.read_field("openbao:secret/ingestion-framework/db#password") == "plain-kv1-value"


def test_resolve_env_or_secret_allows_env_value_to_be_openbao_reference(monkeypatch):
    monkeypatch.setenv("OPENBAO_ADDR", "http://openbao:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "token")
    monkeypatch.setenv(
        "SECRET_REF_ENV",
        "openbao:secret/data/ingestion-framework/minio#secret_key",
    )

    monkeypatch.setattr(
        "ingestion_framework.secrets.openbao.requests.Session",
        lambda: FakeSession({"data": {"data": {"secret_key": "resolved-secret"}}}),
    )

    assert resolve_env_or_secret("SECRET_REF_ENV", label="S3 secret key") == "resolved-secret"


def test_resolve_env_or_secret_rejects_missing_env(monkeypatch):
    monkeypatch.delenv("MISSING_SECRET", raising=False)

    with pytest.raises(RuntimeError, match="Required environment variable is not set"):
        resolve_env_or_secret("MISSING_SECRET", label="missing secret")


class FakeSession:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests = []

    def get(self, url: str, headers: dict[str, str], timeout: int):
        self.requests.append((url, headers, timeout))
        return FakeResponse(self.payload)


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self.payload
