"""Generated from configs/sources/database_compact_generated/itron_mv90_cmmastst_customer_master.yaml; do not edit by hand."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id='ingest_itron_mv90_itron_mv90_cmmastst_customer_master',
    description='Ingest itron_mv90_cmmastst_customer_master from itron_mv90.',
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ingestion-framework', 'database', 'itron_mv90', 'ongoing'],
) as dag:
    run_ingestion = BashOperator(
        task_id="run_ingestion",
        bash_command='ingest-object run-object --config /opt/ingestion-framework/configs/sources/database_compact_generated/itron_mv90_cmmastst_customer_master.yaml --storage /opt/ingestion-framework/configs/storage_minio.yaml --audit-db env:INGESTION_AUDIT_DB_URL',
        append_env=True,
        retries=1,
        retry_delay=timedelta(minutes=5),
    )
