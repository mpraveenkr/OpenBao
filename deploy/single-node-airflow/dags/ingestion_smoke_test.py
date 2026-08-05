from __future__ import annotations

import os
from datetime import datetime

from airflow.decorators import dag, task


@dag(
    dag_id="ingestion_framework_smoke_test",
    description="Validates the ingestion framework runtime and MinIO bronze access.",
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    tags=["ingestion-framework", "smoke-test"],
)
def ingestion_framework_smoke_test():
    @task
    def verify_runtime() -> dict[str, str]:
        import boto3
        import ingestion_framework

        scheme = os.environ.get("MINIO_SCHEME", "http")
        endpoint_url = f"{scheme}://minio:9000"
        bucket = os.environ["MINIO_BRONZE_BUCKET"]

        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=os.environ["MINIO_ROOT_USER"],
            aws_secret_access_key=os.environ["MINIO_ROOT_PASSWORD"],
        )
        key = "_healthcheck/airflow_ingestion_framework_smoke_test.txt"
        client.put_object(Bucket=bucket, Key=key, Body=b"ok\n")
        client.head_object(Bucket=bucket, Key=key)
        return {
            "framework_package": ingestion_framework.__name__,
            "bucket": bucket,
            "key": key,
        }

    verify_runtime()


ingestion_framework_smoke_test()
