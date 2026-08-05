"""Generated from configs/sources/api_generated/weather_forecast.yaml; do not edit by hand."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator


with DAG(
    dag_id='ingest_open_meteo_weather_forecast',
    description='Ingest weather_forecast from open_meteo.',
    schedule=None,
    start_date=datetime(2024, 1, 1),
    catchup=False,
    max_active_runs=1,
    tags=['ingestion-framework', 'api', 'open_meteo', 'ongoing'],
) as dag:
    run_ingestion = BashOperator(
        task_id="run_ingestion",
        bash_command='ingest-object run-object --config /opt/ingestion-framework/configs/sources/api_generated/weather_forecast.yaml --storage /opt/ingestion-framework/configs/storage_minio.yaml --audit-db env:INGESTION_AUDIT_DB_URL',
        append_env=True,
        retries=1,
        retry_delay=timedelta(minutes=5),
    )
