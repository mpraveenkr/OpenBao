from __future__ import annotations

import pytest

from ingestion_framework.config.loader import ConfigLoader
from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.secrets.preflight import collect_requirements
from ingestion_framework.writers.storage import adls_gen2
from ingestion_framework.writers.storage.adls_gen2 import AdlsGen2StorageWriter, build_credential
from ingestion_framework.writers.storage.factory import build_storage_writer


def test_example_adls_config_loads():
    storage = ConfigLoader().load_storage("configs/storage_adls.yaml").storages["adls_bronze"]

    assert storage.type == "adls_gen2"
    assert storage.filesystem == "bronze"
    assert storage.auth_method == "service_principal"
    assert storage.client_secret_ref == (
        "openbao:secret/data/ingestion-framework/adls#client_secret"
    )
    # BCSI sources require storage that reports encryption support.
    assert storage.encryption.supported is True


def test_example_adls_config_holds_no_inline_secret():
    raw = open("configs/storage_adls.yaml").read()

    assert "client_secret:" not in raw
    assert "account_key:" not in raw


def test_writer_builds_abfss_uris_and_applies_prefix(tmp_path):
    source_file = tmp_path / "part-00001.parquet"
    source_file.write_bytes(b"parquet-bytes")
    client = FakeFileSystemClient()
    writer = AdlsGen2StorageWriter(adls_config(), file_system_client=client)

    file_uri = writer.write_file(source_file, "source_type=api/run_id=1/part-00001.parquet")
    manifest_uri = writer.write_bytes(b"{}", "source_type=api/run_id=1/_manifest.json")

    account = "abfss://bronze@examplelake.dfs.core.windows.net"
    assert file_uri == f"{account}/bronze/source_type=api/run_id=1/part-00001.parquet"
    assert manifest_uri == f"{account}/bronze/source_type=api/run_id=1/_manifest.json"
    assert [upload.path for upload in client.uploads] == [
        "bronze/source_type=api/run_id=1/part-00001.parquet",
        "bronze/source_type=api/run_id=1/_manifest.json",
    ]
    assert [upload.data for upload in client.uploads] == [b"parquet-bytes", b"{}"]


def test_writer_overwrites_so_a_retried_run_can_replace_a_partial_file(tmp_path):
    source_file = tmp_path / "part.parquet"
    source_file.write_bytes(b"x")
    client = FakeFileSystemClient()
    writer = AdlsGen2StorageWriter(adls_config(), file_system_client=client)

    writer.write_file(source_file, "run_id=1/part.parquet")

    assert client.uploads[0].overwrite is True


def test_writer_without_a_prefix_writes_at_the_filesystem_root():
    client = FakeFileSystemClient()
    writer = AdlsGen2StorageWriter(
        adls_config(base_prefix=""), file_system_client=client
    )

    uri = writer.write_bytes(b"{}", "run_id=1/_manifest.json")

    assert uri == "abfss://bronze@examplelake.dfs.core.windows.net/run_id=1/_manifest.json"
    assert client.uploads[0].path == "run_id=1/_manifest.json"


@pytest.mark.parametrize("storage_type", ["adls_gen2", "adls"])
def test_factory_dispatches_adls_types(storage_type, monkeypatch):
    monkeypatch.setattr(
        adls_gen2.AdlsGen2StorageWriter,
        "_create_file_system_client",
        lambda self, config: FakeFileSystemClient(),
    )

    writer = build_storage_writer(adls_config(type=storage_type))

    assert isinstance(writer, AdlsGen2StorageWriter)


def test_service_principal_credential_uses_the_resolved_secret(monkeypatch):
    monkeypatch.setattr(adls_gen2, "resolve_secret_reference", lambda ref: "resolved-secret")

    credential = build_credential(adls_config())

    from azure.identity import ClientSecretCredential

    assert isinstance(credential, ClientSecretCredential)


def test_account_key_credential_is_resolved(monkeypatch):
    monkeypatch.setattr(adls_gen2, "resolve_secret_reference", lambda ref: "resolved-key")

    credential = build_credential(
        adls_config(
            auth_method="account_key",
            account_key_ref="openbao:secret/data/ingestion-framework/adls#account_key",
        )
    )

    assert credential == "resolved-key"


def test_inline_client_secret_is_rejected():
    # The whole point of client_secret_ref is that the credential cannot be
    # committed to a config file.
    with pytest.raises(ValueError, match="Unsupported secret reference"):
        build_credential(adls_config(client_secret_ref="plaintext-secret"))


def test_unsupported_auth_method_is_rejected():
    config = adls_config()
    object.__setattr__(config, "auth_method", "managed_identity")

    with pytest.raises(ValueError, match="Unsupported adls_gen2 auth_method"):
        build_credential(config)


def test_config_requires_account_and_filesystem():
    with pytest.raises(ValueError, match="account_name, filesystem"):
        StorageConfig.model_validate({"type": "adls_gen2"})


def test_config_requires_service_principal_fields():
    with pytest.raises(ValueError, match="tenant_id, client_id, client_secret_ref"):
        StorageConfig.model_validate(
            {"type": "adls_gen2", "account_name": "lake", "filesystem": "bronze"}
        )


def test_config_requires_account_key_when_selected():
    with pytest.raises(ValueError, match="account_key_ref"):
        StorageConfig.model_validate(
            {
                "type": "adls_gen2",
                "account_name": "lake",
                "filesystem": "bronze",
                "auth_method": "account_key",
            }
        )


def test_config_rejects_unknown_auth_method():
    with pytest.raises(ValueError, match="Unsupported ADLS Gen2 auth_method"):
        StorageConfig.model_validate(
            {
                "type": "adls_gen2",
                "account_name": "lake",
                "filesystem": "bronze",
                "auth_method": "managed_identity",
            }
        )


def test_s3_validation_message_is_unchanged():
    with pytest.raises(ValueError, match="S3-compatible storage requires: "):
        StorageConfig.model_validate({"type": "s3_compatible"})


def test_check_secrets_covers_the_client_secret():
    requirements = collect_requirements(None, adls_config(), None)

    assert [requirement.location for requirement in requirements] == [
        "openbao:secret/data/ingestion-framework/adls#client_secret"
    ]


def test_check_secrets_covers_the_account_key():
    requirements = collect_requirements(
        None,
        adls_config(
            auth_method="account_key",
            account_key_ref="openbao:secret/data/ingestion-framework/adls#account_key",
        ),
        None,
    )

    assert [requirement.label for requirement in requirements] == ["ADLS account key"]


def test_check_secrets_includes_identifiers_only_when_they_are_references():
    inline = collect_requirements(None, adls_config(), None)
    referenced = collect_requirements(
        None,
        adls_config(tenant_id="openbao:secret/data/ingestion-framework/adls#tenant_id"),
        None,
    )

    assert len(inline) == 1
    assert [requirement.label for requirement in referenced] == [
        "ADLS client secret",
        "ADLS tenant id",
    ]


def adls_config(**overrides) -> StorageConfig:
    values = {
        "type": "adls_gen2",
        "account_name": "examplelake",
        "filesystem": "bronze",
        "base_prefix": "bronze",
        "auth_method": "service_principal",
        "tenant_id": "00000000-0000-0000-0000-000000000000",
        "client_id": "11111111-1111-1111-1111-111111111111",
        "client_secret_ref": "openbao:secret/data/ingestion-framework/adls#client_secret",
        "encryption": {"supported": True, "mode": "microsoft_managed"},
    }
    values.update(overrides)
    return StorageConfig.model_validate(values)


class Upload:
    def __init__(self, path: str, data: bytes, overwrite: bool) -> None:
        self.path = path
        self.data = data
        self.overwrite = overwrite


class FakeFileSystemClient:
    def __init__(self) -> None:
        self.uploads: list[Upload] = []

    def get_file_client(self, path: str):
        return FakeFileClient(self, path)


class FakeFileClient:
    def __init__(self, file_system: FakeFileSystemClient, path: str) -> None:
        self.file_system = file_system
        self.path = path

    def upload_data(self, data, overwrite: bool = False) -> None:
        payload = data if isinstance(data, bytes) else data.read()
        self.file_system.uploads.append(Upload(self.path, payload, overwrite))
