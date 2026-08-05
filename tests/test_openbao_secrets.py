from __future__ import annotations

import pytest
import requests

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
    assert len(session.requests) == 1
    assert session.requests[0]["url"] == (
        "http://openbao:8200/v1/secret/data/ingestion-framework/minio"
    )
    assert session.requests[0]["headers"] == {"X-Vault-Token": "token"}
    assert session.requests[0]["timeout"] == 30


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


def test_reading_two_fields_of_one_secret_makes_a_single_request():
    session = FakeSession(
        {"data": {"data": {"access_key": "minio-user", "secret_key": "minio-password"}}}
    )
    client = OpenBaoClient(addr="http://openbao:8200", token="token", session=session)

    assert client.read_field("openbao:secret/data/app/minio#access_key") == "minio-user"
    assert client.read_field("openbao:secret/data/app/minio#secret_key") == "minio-password"

    assert len(session.requests) == 1


def test_clear_cache_forces_a_refetch():
    session = FakeSession({"data": {"data": {"access_key": "minio-user"}}})
    client = OpenBaoClient(addr="http://openbao:8200", token="token", session=session)

    client.read_field("openbao:secret/data/app/minio#access_key")
    client.clear_cache()
    client.read_field("openbao:secret/data/app/minio#access_key")

    assert len(session.requests) == 2


def test_distinct_paths_are_cached_separately():
    session = FakeSession({"data": {"data": {"value": "x"}}})
    client = OpenBaoClient(addr="http://openbao:8200", token="token", session=session)

    client.read_field("openbao:secret/data/app/one#value")
    client.read_field("openbao:secret/data/app/two#value")

    assert [request["url"] for request in session.requests] == [
        "http://openbao:8200/v1/secret/data/app/one",
        "http://openbao:8200/v1/secret/data/app/two",
    ]


def test_ca_certificate_is_passed_as_verify(monkeypatch, tmp_path):
    ca_file = tmp_path / "ca.crt"
    ca_file.write_text("-----BEGIN CERTIFICATE-----\n")
    monkeypatch.setenv("OPENBAO_CACERT", str(ca_file))

    session = FakeSession({"data": {"data": {"value": "secret"}}})
    client = OpenBaoClient(addr="https://openbao:8200", token="token", session=session)
    client.read_field("openbao:secret/data/app/thing#value")

    assert session.requests[0]["verify"] == str(ca_file)


def test_missing_ca_certificate_is_rejected(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENBAO_CACERT", str(tmp_path / "absent.crt"))

    with pytest.raises(RuntimeError, match="CA certificate file does not exist"):
        OpenBaoClient(addr="https://openbao:8200", token="token", session=FakeSession({}))


def test_verification_is_skipped_only_when_explicitly_requested(monkeypatch):
    monkeypatch.delenv("OPENBAO_CACERT", raising=False)
    monkeypatch.setenv("OPENBAO_SKIP_VERIFY", "true")

    session = FakeSession({"data": {"data": {"value": "secret"}}})
    client = OpenBaoClient(addr="https://openbao:8200", token="token", session=session)
    client.read_field("openbao:secret/data/app/thing#value")

    assert session.requests[0]["verify"] is False


def test_verification_is_on_by_default(monkeypatch):
    monkeypatch.delenv("OPENBAO_CACERT", raising=False)
    monkeypatch.delenv("OPENBAO_SKIP_VERIFY", raising=False)

    session = FakeSession({"data": {"data": {"value": "secret"}}})
    client = OpenBaoClient(addr="https://openbao:8200", token="token", session=session)
    client.read_field("openbao:secret/data/app/thing#value")

    assert session.requests[0]["verify"] is True


def test_transient_server_error_is_retried():
    session = FakeSession({"data": {"data": {"value": "secret"}}}, outcomes=[503, 200])
    client = OpenBaoClient(
        addr="http://openbao:8200",
        token="token",
        session=session,
        retry_backoff_seconds=0,
    )

    assert client.read_field("openbao:secret/data/app/thing#value") == "secret"
    assert len(session.requests) == 2


def test_connection_error_is_retried():
    session = FakeSession(
        {"data": {"data": {"value": "secret"}}},
        outcomes=[requests.ConnectionError("openbao restarting"), 200],
    )
    client = OpenBaoClient(
        addr="http://openbao:8200",
        token="token",
        session=session,
        retry_backoff_seconds=0,
    )

    assert client.read_field("openbao:secret/data/app/thing#value") == "secret"
    assert len(session.requests) == 2


def test_retries_are_bounded():
    session = FakeSession({}, outcomes=[requests.ConnectionError("down")] * 5)
    client = OpenBaoClient(
        addr="http://openbao:8200",
        token="token",
        session=session,
        max_attempts=3,
        retry_backoff_seconds=0,
    )

    with pytest.raises(RuntimeError, match="after 3 attempts"):
        client.read_field("openbao:secret/data/app/thing#value")
    assert len(session.requests) == 3


def test_permission_errors_are_not_retried():
    session = FakeSession({}, outcomes=[403, 200])
    client = OpenBaoClient(
        addr="http://openbao:8200",
        token="token",
        session=session,
        retry_backoff_seconds=0,
    )

    with pytest.raises(requests.HTTPError):
        client.read_field("openbao:secret/data/app/thing#value")
    assert len(session.requests) == 1


class FakeSession:
    """Stand-in for requests.Session that records calls and can script failures."""

    def __init__(self, payload: dict, outcomes: list | None = None) -> None:
        self.payload = payload
        self.requests: list[dict] = []
        self.outcomes = list(outcomes or [])

    def get(self, url: str, headers: dict[str, str], timeout: int, verify=True):
        self.requests.append(
            {"url": url, "headers": headers, "timeout": timeout, "verify": verify}
        )
        outcome = self.outcomes.pop(0) if self.outcomes else 200
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(self.payload, status_code=outcome)


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status {self.status_code}")

    def json(self) -> dict:
        return self.payload
