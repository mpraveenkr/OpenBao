from __future__ import annotations

from pathlib import Path

from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.secrets import resolve_secret_reference, resolve_value
from ingestion_framework.writers.storage.base import BaseStorageWriter

SERVICE_PRINCIPAL = "service_principal"
ACCOUNT_KEY = "account_key"
SUPPORTED_AUTH_METHODS = (SERVICE_PRINCIPAL, ACCOUNT_KEY)


class AdlsGen2StorageWriter(BaseStorageWriter):
    """Writes objects to Azure Data Lake Storage Gen2."""

    def __init__(self, config: StorageConfig, file_system_client=None) -> None:
        self.config = config
        self.account_name = require_value(config.account_name, "account_name")
        self.filesystem = require_value(config.filesystem, "filesystem")
        self.base_prefix = (config.base_prefix or "").strip("/")
        self.file_system_client = file_system_client or self._create_file_system_client(config)

    def write_file(self, source_file: str | Path, target_key: str) -> str:
        path = self._object_path(target_key)
        with open(source_file, "rb") as handle:
            self._upload(path, handle)
        return self._uri(path)

    def write_bytes(self, content: bytes, target_key: str) -> str:
        path = self._object_path(target_key)
        self._upload(path, content)
        return self._uri(path)

    def _upload(self, path: str, data) -> None:
        file_client = self.file_system_client.get_file_client(path)
        # Bronze output is immutable under a unique run_id, so overwriting only
        # ever replaces a partial file left by a failed attempt.
        file_client.upload_data(data, overwrite=True)

    def _object_path(self, target_key: str) -> str:
        cleaned = str(target_key).lstrip("/")
        if self.base_prefix:
            return f"{self.base_prefix}/{cleaned}"
        return cleaned

    def _uri(self, path: str) -> str:
        return f"abfss://{self.filesystem}@{self.account_name}.dfs.core.windows.net/{path}"

    def _create_file_system_client(self, config: StorageConfig):
        try:
            from azure.storage.filedatalake import DataLakeServiceClient
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "azure-storage-file-datalake is required for adls_gen2 storage. "
                "Install the project dependencies in the runtime container before "
                "using Azure Data Lake storage."
            ) from exc

        account_url = config.endpoint_url or f"https://{self.account_name}.dfs.core.windows.net"
        service_client = DataLakeServiceClient(
            account_url=account_url,
            credential=build_credential(config),
        )
        return service_client.get_file_system_client(self.filesystem)


def build_credential(config: StorageConfig):
    """Build an ADLS credential, sourcing the secret half from OpenBao.

    Tenant and client IDs are identifiers rather than secrets, so they may be
    written inline or as OpenBao references. The client secret and account key
    must be references, so a credential cannot be committed to a config file.
    """
    auth_method = (config.auth_method or SERVICE_PRINCIPAL).strip()

    if auth_method == ACCOUNT_KEY:
        return resolve_secret_reference(require_value(config.account_key_ref, "account_key_ref"))

    if auth_method == SERVICE_PRINCIPAL:
        try:
            from azure.identity import ClientSecretCredential
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "azure-identity is required for adls_gen2 service principal auth. "
                "Install the project dependencies in the runtime container before "
                "using Azure Data Lake storage."
            ) from exc

        return ClientSecretCredential(
            tenant_id=resolve_value(require_value(config.tenant_id, "tenant_id")),
            client_id=resolve_value(require_value(config.client_id, "client_id")),
            client_secret=resolve_secret_reference(
                require_value(config.client_secret_ref, "client_secret_ref")
            ),
        )

    raise ValueError(
        f"Unsupported adls_gen2 auth_method: {auth_method}. "
        f"Supported values are: {', '.join(SUPPORTED_AUTH_METHODS)}"
    )


def require_value(value: str | None, name: str) -> str:
    if value is None or str(value).strip() == "":
        raise ValueError(f"ADLS Gen2 storage missing required {name}")
    return str(value).strip()
