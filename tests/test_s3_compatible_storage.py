from __future__ import annotations

from pathlib import Path

from ingestion_framework.config.loader import ConfigLoader
from ingestion_framework.config.validator import StorageConfig
from ingestion_framework.writers.storage.s3_compatible import S3CompatibleStorageWriter


def test_minio_storage_config_loads():
    storage = ConfigLoader().load_storage("configs/storage_minio.yaml").storages["minio_bronze"]

    assert storage.type == "s3_compatible"
    assert storage.bucket == "bronze"
    assert storage.base_prefix == "bronze"
    assert storage.endpoint_url == "http://minio:9000"
    assert storage.access_key_ref == "openbao:secret/data/ingestion-framework/minio#access_key"


def test_s3_compatible_writer_uploads_file_and_bytes(tmp_path):
    source_file = tmp_path / "part-00001.parquet"
    source_file.write_bytes(b"parquet-bytes")
    client = FakeS3Client()
    writer = S3CompatibleStorageWriter(
        StorageConfig(
            type="s3_compatible",
            bucket="bronze",
            base_prefix="bronze",
            endpoint_url="http://minio:9000",
            access_key_ref="openbao:secret/data/ingestion-framework/minio#access_key",
            secret_key_ref="openbao:secret/data/ingestion-framework/minio#secret_key",
        ),
        client=client,
    )

    file_uri = writer.write_file(source_file, "source_type=api/run_id=1/part-00001.parquet")
    manifest_uri = writer.write_bytes(b"{}", "source_type=api/run_id=1/_manifest.json")

    assert file_uri == "s3://bronze/bronze/source_type=api/run_id=1/part-00001.parquet"
    assert manifest_uri == "s3://bronze/bronze/source_type=api/run_id=1/_manifest.json"
    assert client.uploads == [
        (
            str(source_file),
            "bronze",
            "bronze/source_type=api/run_id=1/part-00001.parquet",
        )
    ]
    assert client.objects == [
        ("bronze", "bronze/source_type=api/run_id=1/_manifest.json", b"{}")
    ]

class FakeS3Client:
    def __init__(self) -> None:
        self.uploads = []
        self.objects = []

    def upload_file(self, filename: str, bucket: str, key: str) -> None:
        self.uploads.append((filename, bucket, key))

    def put_object(self, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects.append((Bucket, Key, Body))
