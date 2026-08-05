"""Generated from configs/sources/sample_csv_customers.yaml; do not edit by hand."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id='ingest_sample_files_sample_csv_customers',
    description='Ingest sample_csv_customers from sample_files.',
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ingestion-framework', 'file', 'sample_files', 'ongoing'],
) as dag:
    run_ingestion = BashOperator(
        task_id="run_ingestion",
        bash_command='ingest-object run-object --config /opt/ingestion-framework/configs/sources/sample_csv_customers.yaml --storage /opt/ingestion-framework/configs/storage_minio.yaml --audit-db env:INGESTION_AUDIT_DB_URL',
        append_env=True,
        retries=1,
        retry_delay=timedelta(minutes=5),
    )
