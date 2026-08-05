from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import requests

from ingestion_framework.connectors.api import format_runtime_date, request_with_retries
from ingestion_framework.config.validator import SourceObjectConfig, StorageConfig
from ingestion_framework.processors.api import ApiProcessor
from ingestion_framework.processors.base import ProcessorContext


def test_api_processor_handles_paginated_record_array(tmp_path):
    source = SourceObjectConfig.model_validate(
        {
            "object_id": "pjm_hrl_load_metered",
            "source_system": "pjm",
            "source_type": "api",
            "object_name": "hrl_load_metered",
            "load_strategy": "full",
            "extraction": {
                "base_url": "https://api.example.test",
                "endpoint": "/loads",
                "method": "GET",
                "auth_type": "none",
                "pagination": {
                    "type": "offset_limit",
                    "offset_param": "startRow",
                    "limit_param": "rowCount",
                    "start": 1,
                    "increment": 2,
                },
                "query_parameters": {
                    "rowCount": {"value_template": 2, "type": "integer", "required": True},
                    "startRow": {"value_template": "{startRow}", "type": "integer", "required": True},
                },
                "runtime_parameters": [
                    {
                        "name": "startRow",
                        "type": "integer",
                        "default_strategy": "pagination_counter",
                    }
                ],
                "response_record_path": "$.items[*]",
            },
            "schema": {
                "columns": {
                    "datetime_beginning_utc": {
                        "type": "timestamp",
                        "nullable": False,
                        "source_json_path": "datetime_beginning_utc",
                    },
                    "zone": {
                        "type": "string",
                        "nullable": False,
                        "source_json_path": "zone",
                    },
                    "mw": {
                        "type": "float",
                        "nullable": False,
                        "source_json_path": "mw",
                    },
                }
            },
            "target": {
                "storage_name": "local_bronze",
                "zone": "bronze",
                "format": "parquet",
                "write_mode": "append",
                "compression": "snappy",
                "partition_by": ["ingest_year", "ingest_month", "ingest_day"],
            },
            "security": security(),
        }
    )
    storage = local_storage(tmp_path)
    session = FakeSession(
        [
            {"items": [{"datetime_beginning_utc": "2026-07-01T00:00:00Z", "zone": "AE", "mw": 100.5}]},
            {"items": []},
        ]
    )

    result = ApiProcessor(session=session).run(
        ProcessorContext(source=source, storage=storage, run_id="run-1", base_dir=tmp_path)
    )

    assert result.rows_extracted == 1
    assert result.rows_written == 1
    assert Path(result.target_path).exists()
    assert Path(result.manifest_path).exists()
    assert session.calls[0]["params"]["startRow"] == 1
    manifest = json.loads(Path(result.manifest_path).read_text())
    assert manifest["source_type"] == "api"
    frame = pd.read_parquet(result.target_path)
    assert frame.loc[0, "zone"] == "AE"


def test_api_processor_handles_parameter_set_timeseries(tmp_path):
    station_path = tmp_path / "data" / "input" / "stations.csv"
    station_path.parent.mkdir(parents=True)
    station_path.write_text("val_lat,val_lon\n33.0,-97.0\n", encoding="utf-8")
    source = SourceObjectConfig.model_validate(
        {
            "object_id": "weather_forecast",
            "source_system": "open_meteo",
            "source_type": "api",
            "object_name": "weather_forecast",
            "load_strategy": "full",
            "extraction": {
                "base_url": "https://api.example.test",
                "endpoint": "/forecast",
                "method": "GET",
                "auth_type": "none",
                "pagination": {"type": "none"},
                "query_parameters": {
                    "latitude": {"value_template": "{latitude}", "type": "float", "required": True},
                    "longitude": {"value_template": "{longitude}", "type": "float", "required": True},
                    "start_date": {"value_template": "{start_date}", "type": "date", "required": True},
                },
                "runtime_parameters": [
                    {"name": "latitude", "default_strategy": "parameter_set_value"},
                    {"name": "longitude", "default_strategy": "parameter_set_value"},
                    {"name": "start_date", "default_strategy": "current_date", "offset_days": 0},
                ],
                "parameter_sets": [
                    {
                        "set_name": "stations",
                        "type": "file",
                        "file_type": "csv",
                        "path": "data/input/stations.csv",
                        "mode": "one_request_per_row",
                        "columns": [
                            {"column_name": "val_lat", "maps_to": "runtime.latitude"},
                            {"column_name": "val_lon", "maps_to": "runtime.longitude"},
                        ],
                    }
                ],
                "response_shape": "timeseries_arrays",
                "time_path": "$.hourly.time[*]",
                "array_parent_path": "$.hourly",
            },
            "schema": {
                "columns": {
                    "tm_start": {
                        "type": "timestamp",
                        "nullable": False,
                        "source_json_path": "$.hourly.time[*]",
                    },
                    "val_latitude": {
                        "type": "float",
                        "nullable": False,
                        "source_json_path": "$.latitude",
                    },
                    "val_temperature_2m": {
                        "type": "float",
                        "nullable": True,
                        "source_json_path": "$.hourly.temperature_2m[*]",
                    },
                }
            },
            "schema_policy": {"include_unmodeled_columns": True},
            "target": {
                "storage_name": "local_bronze",
                "zone": "bronze",
                "format": "parquet",
                "write_mode": "append",
                "compression": "snappy",
                "partition_by": ["ingest_year", "ingest_month", "ingest_day"],
            },
            "security": security(),
        }
    )
    session = FakeSession(
        [
            {
                "latitude": 33.0,
                "longitude": -97.0,
                "elevation": 200,
                "timezone": "UTC",
                "daily": {"time": ["2026-07-01"]},
                "hourly": {
                    "time": ["2026-07-01T00:00", "2026-07-01T01:00"],
                    "temperature_2m": [21.1, 22.2],
                },
            }
        ]
    )

    result = ApiProcessor(session=session).run(
        ProcessorContext(source=source, storage=local_storage(tmp_path), run_id="run-2", base_dir=tmp_path)
    )

    assert result.rows_extracted == 2
    frame = pd.read_parquet(result.target_path)
    assert frame["val_temperature_2m"].tolist() == [21.1, 22.2]
    assert frame["val_latitude"].tolist() == [33.0, 33.0]
    assert "time" in frame.columns
    assert session.calls[0]["params"]["latitude"] == 33.0
    assert session.calls[0]["params"]["longitude"] == -97.0


def test_api_processor_handles_page_number_pagination_and_nested_records(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENBAO_ADDR", "http://openbao:8200")
    monkeypatch.setenv("OPENBAO_TOKEN", "token")
    monkeypatch.setattr(
        "ingestion_framework.secrets.openbao.requests.Session",
        lambda: FakeOpenBaoSession(
            {"data": {"data": {"subscription_key": "secret"}}}
        ),
    )
    source = SourceObjectConfig.model_validate(
        {
            "object_id": "miso_forecast",
            "source_system": "miso",
            "source_type": "api",
            "object_name": "forecast",
            "load_strategy": "full",
            "extraction": {
                "base_url": "https://api.example.test",
                "endpoint": "/forecast/{date}/load",
                "method": "GET",
                "auth_type": "api_key_header",
                "connection_name": "miso_apim_subscription",
                "api_key_header_name": "Ocp-Apim-Subscription-Key",
                "api_key_secret_ref": "openbao:secret/data/ingestion-framework/api/miso#subscription_key",
                "pagination": {
                    "type": "page_number",
                    "param": "pageNumber",
                    "start": 1,
                    "increment": 1,
                    "max_pages": 3,
                },
                "query_parameters": {
                    "pageNumber": {"value_template": "{pageNumber}", "type": "integer", "required": True},
                    "timeResolution": {"value_template": "hourly", "type": "string", "required": True},
                },
                "runtime_parameters": [
                    {"name": "date", "location": "path", "type": "date", "default_strategy": "static", "default_value": "2026-07-01"},
                    {"name": "pageNumber", "location": "query", "type": "integer", "default_strategy": "pagination_counter"},
                ],
                "response_record_path": "$.data[*]",
                "retry_count": 1,
                "timeout_seconds": 30,
            },
            "schema": {
                "columns": {
                    "start": {
                        "type": "timestamp",
                        "nullable": False,
                        "source_json_path": "timeInterval.start",
                    },
                    "region": {
                        "type": "string",
                        "nullable": False,
                        "source_json_path": "region",
                    },
                    "load_forecast": {
                        "type": "float",
                        "nullable": True,
                        "source_json_path": "loadForecast",
                    },
                }
            },
            "schema_policy": {"include_unmodeled_columns": True},
            "target": {
                "storage_name": "local_bronze",
                "zone": "bronze",
                "format": "parquet",
                "write_mode": "append",
                "compression": "snappy",
                "partition_by": ["ingest_year", "ingest_month", "ingest_day"],
            },
            "security": security(),
        }
    )
    session = FakeSession(
        [
            {
                "data": [
                    {
                        "timeInterval": {"start": "2026-07-01T00:00:00Z", "end": "2026-07-01T01:00:00Z"},
                        "region": "MISO",
                        "loadForecast": 1200.5,
                    }
                ]
            },
            {"data": []},
        ]
    )

    result = ApiProcessor(session=session).run(
        ProcessorContext(source=source, storage=local_storage(tmp_path), run_id="run-3", base_dir=tmp_path)
    )

    assert result.rows_written == 1
    assert session.calls[0]["url"].endswith("/forecast/2026-07-01/load")
    assert session.calls[0]["params"]["pageNumber"] == 1
    assert session.calls[1]["params"]["pageNumber"] == 2
    assert session.calls[0]["headers"]["Ocp-Apim-Subscription-Key"] == "secret"
    frame = pd.read_parquet(result.target_path)
    assert frame.loc[0, "region"] == "MISO"
    assert frame.loc[0, "time_interval_end"] == "2026-07-01T01:00:00Z"


def test_format_runtime_date_supports_non_iso_formats():
    formatted = format_runtime_date(0, "MM/DD/YYYY")

    assert len(formatted) == 10
    assert formatted[2] == "/"
    assert formatted[5] == "/"


def test_request_with_retries_does_not_retry_401():
    response = FakeErrorResponse(401)
    session = FakeErrorSession(response)
    source = SourceObjectConfig.model_validate(
        {
            "object_id": "bad_auth",
            "source_system": "test",
            "source_type": "api",
            "object_name": "bad_auth",
            "load_strategy": "full",
            "extraction": {
                "base_url": "https://api.example.test",
                "endpoint": "/bad-auth",
                "method": "GET",
                "auth_type": "none",
                "response_record_path": "$.items[*]",
                "retry_count": 3,
            },
            "schema": {"columns": {}},
            "target": {
                "storage_name": "local_bronze",
                "zone": "bronze",
                "format": "parquet",
                "write_mode": "append",
                "compression": "snappy",
            },
            "security": security(),
        }
    )

    with pytest.raises(requests.exceptions.HTTPError):
        request_with_retries(session, source, "https://api.example.test/bad-auth", {}, {})

    assert session.calls == 1


def local_storage(tmp_path) -> StorageConfig:
    return StorageConfig(
        type="local",
        base_path=str(tmp_path / "output"),
        encryption={"supported": False, "mode": "none"},
    )


def security():
    return {
        "classification": "internal",
        "contains_bcsi": False,
        "contains_pii": False,
        "encryption_required": False,
        "masking_required": False,
        "raw_payload_retention_days": 30,
        "access_group": "data_platform_users",
    }


class FakeSession:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append({"url": url, "params": params or {}, "headers": headers or {}, "timeout": timeout})
        return FakeResponse(self.payloads.pop(0))


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeOpenBaoSession:
    def __init__(self, payload):
        self.payload = payload

    def get(self, url, headers=None, timeout=None):
        return FakeResponse(self.payload)


class FakeErrorSession:
    def __init__(self, response):
        self.response = response
        self.calls = 0

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls += 1
        return self.response


class FakeErrorResponse:
    def __init__(self, status_code: int):
        self.status_code = status_code

    def raise_for_status(self):
        error = requests.exceptions.HTTPError("HTTP error")
        error.response = self
        raise error
