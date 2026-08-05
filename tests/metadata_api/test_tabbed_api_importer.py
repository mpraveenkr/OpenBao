from __future__ import annotations

from argparse import Namespace

import yaml
from openpyxl import Workbook

from ingestion_framework.config.validator import SourceObjectConfig
from metadata_api.tabbed_api_importer import TabbedApiWorkbookImporter
from tools.import_api_templates import import_folder


def test_tabbed_api_importer_loads_record_array_workbook(tmp_path):
    workbook_path = make_api_workbook(tmp_path / "PJM_Load_Forecast_Template.xlsx")

    config = TabbedApiWorkbookImporter().load(workbook_path)
    validated = SourceObjectConfig.model_validate(config)

    assert config["object_id"] == "pjm_load_forecast"
    assert config["source_system"] == "pjm"
    assert config["extraction"]["response_record_path"] == "$.items[*]"
    assert config["extraction"]["query_parameters"]["rowCount"]["value_template"] == 50000
    assert config["extraction"]["runtime_parameters"][0]["name"] == "startRow"
    assert config["schema"]["columns"]["datetime_beginning_utc"]["source_json_path"] == "datetime_beginning_utc"
    assert config["audit"]["primary_key"] == ["datetime_beginning_utc", "zone"]
    assert validated.extraction.base_url == "https://api.pjm.com/api/v1"


def test_tabbed_api_importer_loads_parameter_set_timeseries_workbook(tmp_path):
    workbook_path = make_api_workbook(
        tmp_path / "Weather_Forecast Template.xlsx",
        timeseries=True,
    )

    config = TabbedApiWorkbookImporter().load(workbook_path)

    assert config["object_id"] == "weather_forecast"
    assert config["source_system"] == "open_meteo"
    assert config["extraction"]["response_shape"] == "timeseries_arrays"
    assert config["extraction"]["time_path"] == "$.hourly.time[*]"
    assert len(config["extraction"]["parameter_sets"]) == 1
    assert config["extraction"]["parameter_sets"][0]["columns"][0]["maps_to"] == "runtime.latitude"
    assert config["schema_policy"]["response_shape"] == "timeseries_arrays"


def test_api_template_folder_import_writes_yaml(tmp_path):
    input_folder = tmp_path / "api_templates"
    input_folder.mkdir()
    make_api_workbook(input_folder / "PJM_Load_Forecast_Template.xlsx")
    make_api_workbook(input_folder / "Weather_Forecast Template.xlsx", timeseries=True)
    output_dir = tmp_path / "configs"

    report = import_folder(
        Namespace(
            input_folder=str(input_folder),
            output_dir=str(output_dir),
            dry_run=False,
            limit=None,
            report_dir=str(tmp_path / "reports"),
        )
    )

    assert report["objects_processed"] == 2
    assert report["yaml_generated"] == 2
    assert report["failures"] == []
    pjm = yaml.safe_load((output_dir / "pjm_load_forecast.yaml").read_text())
    weather = yaml.safe_load((output_dir / "weather_forecast.yaml").read_text())
    assert pjm["extraction"]["pagination"]["type"] == "offset_limit"
    assert weather["extraction"]["parameter_sets"][0]["path"] == "data/input/stations.csv"


def make_api_workbook(path, timeseries=False):
    workbook = Workbook()
    workbook.remove(workbook.active)
    append_sheet(
        workbook,
        "Ingestion_Template",
        [
            ["field_name", "filled_value", "notes"],
            ["base_url", "https://api.open-meteo.com/v1" if timeseries else "https://api.pjm.com/api/v1", ""],
            ["endpoint", "/forecast" if timeseries else "/load_frcstd_7_day", ""],
            ["method", "GET", ""],
            ["auth_type", "none" if timeseries else "api_key_header", ""],
            ["connection_name", "" if timeseries else "pjm_apim_subscription", ""],
            ["api_key_header_name", "" if timeseries else "Ocp-Apim-Subscription-Key", ""],
            ["pagination_type", "none" if timeseries else "offset_limit", ""],
            ["pagination_offset_param", "" if timeseries else "startRow", ""],
            ["pagination_limit_param", "" if timeseries else "rowCount", ""],
            ["pagination_start", "" if timeseries else 1, ""],
            ["pagination_increment", "" if timeseries else 50000, ""],
            ["response_record_path", "" if timeseries else "$.items[*]", ""],
            ["response_shape", "timeseries_arrays" if timeseries else "", ""],
            ["time_path", "$.hourly.time[*]" if timeseries else "", ""],
            ["array_parent_path", "$.hourly" if timeseries else "", ""],
            ["metadata_paths", "latitude,longitude" if timeseries else "", ""],
            ["rate_limit_per_minute", 60, ""],
            ["timeout_seconds", 30, ""],
            ["retry_count", 3, ""],
        ],
    )
    append_sheet(
        workbook,
        "Query_Parameters",
        [
            ["parameter_name", "value_template", "type", "required", "notes"],
            ["latitude", "{latitude}", "float", True, ""] if timeseries else ["rowCount", 50000, "integer", True, ""],
            ["longitude", "{longitude}", "float", True, ""] if timeseries else ["startRow", "{startRow}", "integer", True, ""],
        ],
    )
    append_sheet(
        workbook,
        "Runtime_Parameters",
        [
            ["parameter_name", "location", "placeholder", "type", "required", "default_strategy", "default_value", "timezone", "format", "offset_days", "notes"],
            ["latitude", "query", "{latitude}", "float", True, "parameter_set_value", "", "", "", "", ""] if timeseries else ["startRow", "query", "startRow", "integer", True, "pagination_counter", 1, "", "", "", ""],
            ["longitude", "query", "{longitude}", "float", True, "parameter_set_value", "", "", "", "", ""] if timeseries else ["", "", "", "", "", "", "", "", "", "", ""],
        ],
    )
    if timeseries:
        append_sheet(
            workbook,
            "Parameter_Sets",
            [
                ["set_name", "type", "file_type", "path", "key_column", "mode", "max_concurrency", "fail_fast", "notes"],
                ["stations", "file", "csv", "data/input/stations.csv", "", "one_request_per_row", 1, False, ""],
            ],
        )
        append_sheet(
            workbook,
            "Parameter_Set_Columns",
            [
                ["set_name", "column_name", "type", "required", "maps_to", "notes"],
                ["stations", "val_lat", "float", True, "runtime.latitude", ""],
                ["stations", "val_lon", "float", True, "runtime.longitude", ""],
            ],
        )
    append_sheet(
        workbook,
        "Schema_Policy",
        [
            ["field_name", "filled_value", "notes"],
            ["mode", "hybrid", ""],
            ["response_shape", "timeseries_arrays" if timeseries else "", ""],
            ["flatten_json", True, ""],
            ["nested_field_separator", "_", ""],
            ["column_case", "snake_case", ""],
            ["include_unmodeled_columns", True, ""],
            ["allow_schema_evolution", True, ""],
        ],
    )
    append_sheet(
        workbook,
        "Schema",
        [
            ["column_name", "source_json_path", "type", "nullable", "primary_key", "mask_policy", "description"],
            ["tm_start", "$.hourly.time[*]", "timestamp", False, True, "none", ""] if timeseries else ["datetime_beginning_utc", "datetime_beginning_utc", "timestamp", "NO", "YES", "none", ""],
            ["val_latitude", "$.latitude", "float", False, True, "none", ""] if timeseries else ["zone", "zone", "string", "NO", "YES", "none", ""],
        ],
    )
    append_sheet(workbook, "Response", [["sample_json"], ["{}"]])
    workbook.save(path)
    return path


def append_sheet(workbook, name, rows):
    worksheet = workbook.create_sheet(name)
    for row in rows:
        worksheet.append(row)
