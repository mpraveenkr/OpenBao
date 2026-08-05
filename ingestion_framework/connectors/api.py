from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ingestion_framework.normalizers.columns import ColumnNormalizer
from ingestion_framework.secrets import resolve_env_or_secret


class ApiExtractor:
    """Extract API records into a DataFrame using source-object metadata."""

    def __init__(
        self,
        source: Any,
        base_dir: str | Path | None = None,
        session: Any | None = None,
    ) -> None:
        self.source = source
        self.base_dir = Path(base_dir) if base_dir else Path.cwd()
        self.session = session

    def extract(self) -> pd.DataFrame:
        source = self.source
        session = self.session or create_requests_session()

        frames = []
        parameter_contexts = build_parameter_contexts(source.extraction, self.base_dir)
        for parameter_context in parameter_contexts:
            pages = fetch_pages(session, source, parameter_context)
            for payload in pages:
                rows = payload_to_rows(payload, source, parameter_context)
                if rows:
                    frames.append(pd.DataFrame(rows))

        if frames:
            return pd.concat(frames, ignore_index=True)
        return pd.DataFrame(columns=list(source.schema.columns.keys()))


def create_requests_session():
    try:
        import requests
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "requests is required for API execution. Install project dependencies in the runtime."
        ) from exc
    return requests.Session()


def build_parameter_contexts(extraction: Any, base_dir: Path) -> list[dict[str, Any]]:
    parameter_sets = get_extra(extraction, "parameter_sets", [])
    if not parameter_sets:
        return [{}]

    contexts = []
    for parameter_set in parameter_sets:
        path = resolve_path(parameter_set.get("path"), base_dir)
        file_type = str(parameter_set.get("file_type", "csv")).lower()
        if file_type != "csv":
            raise ValueError(f"Unsupported parameter set file_type: {file_type}")
        frame = pd.read_csv(path)
        mappings = parameter_set.get("columns", [])
        for _, row in frame.iterrows():
            context = {
                "_parameter_set_name": parameter_set.get("set_name"),
                "_parameter_set_path": str(path),
            }
            for mapping in mappings:
                source_column = mapping.get("column_name")
                maps_to = mapping.get("maps_to", "")
                if not source_column or not maps_to.startswith("runtime."):
                    continue
                if source_column not in row or pd.isna(row[source_column]):
                    if mapping.get("required"):
                        raise ValueError(
                            f"Parameter set {parameter_set.get('set_name')} missing required "
                            f"value for column {source_column}"
                        )
                    continue
                runtime_name = maps_to.split(".", 1)[1]
                context[runtime_name] = row[source_column]
            contexts.append(context)
    return contexts or [{}]


def fetch_pages(session: Any, source: Any, parameter_context: dict[str, Any]) -> list[dict[str, Any]]:
    extraction = source.extraction
    pagination = get_extra(extraction, "pagination", {"type": "none"})
    pagination_type = pagination.get("type", "none")
    max_pages = int(pagination.get("max_pages", 1000))
    rate_limit_per_minute = get_extra(extraction, "rate_limit_per_minute")
    delay_seconds = 60 / int(rate_limit_per_minute) if rate_limit_per_minute else 0
    pages = []

    page_value = int(pagination.get("start") or 1)
    for page_index in range(max_pages):
        runtime_values = resolve_runtime_values(extraction, parameter_context, page_value)
        endpoint = substitute(str(extraction.endpoint), runtime_values)
        url = f"{str(extraction.base_url).rstrip('/')}/{endpoint.lstrip('/')}"
        params = build_query_params(extraction, runtime_values)
        headers = build_headers(source)
        response = request_with_retries(session, source, url, params, headers)
        payload = response.json()
        pages.append(payload)

        if pagination_type == "none":
            break
        records = extract_records(payload, get_extra(extraction, "response_record_path", ""))
        if not records:
            break
        page_value += int(pagination.get("increment") or 1)
        if pagination_type == "offset_limit":
            limit_param = pagination.get("limit_param")
            limit = int(params.get(limit_param, pagination.get("increment") or len(records)))
            if len(records) < limit:
                break
        if delay_seconds and page_index < max_pages - 1:
            time.sleep(delay_seconds)
    return pages


def request_with_retries(
    session: Any,
    source: Any,
    url: str,
    params: dict[str, Any],
    headers: dict[str, str],
) -> Any:
    extraction = source.extraction
    attempts = int(get_extra(extraction, "retry_count", 0) or 0) + 1
    timeout = get_extra(extraction, "timeout_seconds", 30)
    last_error = None
    for attempt in range(attempts):
        try:
            response = session.get(url, params=params, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.HTTPError as exc:
            status_code = exc.response.status_code if exc.response is not None else None
            if status_code in {400, 401, 403, 404}:
                raise
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(min(2**attempt, 30))
        except requests.exceptions.RequestException as exc:
            last_error = exc
            if attempt == attempts - 1:
                break
            time.sleep(min(2**attempt, 30))
    raise last_error


def resolve_runtime_values(
    extraction: Any,
    parameter_context: dict[str, Any],
    pagination_counter: int,
) -> dict[str, Any]:
    values = {}
    for parameter in get_extra(extraction, "runtime_parameters", []):
        name = parameter.get("name")
        if not name:
            continue
        strategy = parameter.get("default_strategy", "")
        if strategy == "parameter_set_value":
            if name not in parameter_context:
                if parameter.get("required"):
                    raise ValueError(f"Missing required parameter_set_value runtime parameter: {name}")
                values[name] = parameter.get("default_value")
            else:
                values[name] = parameter_context[name]
        elif strategy == "pagination_counter":
            values[name] = pagination_counter
        elif strategy == "static":
            values[name] = parameter.get("default_value")
        elif strategy in {"current_date", "days_ahead", "yesterday"}:
            offset_days = int(parameter.get("offset_days") or 0)
            if strategy == "yesterday" and not parameter.get("offset_days"):
                offset_days = -1
            values[name] = format_runtime_date(offset_days, parameter.get("format"))
        else:
            values[name] = parameter.get("default_value")
    return values


def format_runtime_date(offset_days: int, date_format: str | None) -> str:
    value = datetime.now(timezone.utc).date() + timedelta(days=offset_days)
    if date_format in {"yyyy-MM-dd", "YYYY-MM-DD", None, ""}:
        return value.isoformat()
    py_format = (
        str(date_format)
        .replace("yyyy", "%Y")
        .replace("YYYY", "%Y")
        .replace("MM", "%m")
        .replace("dd", "%d")
        .replace("DD", "%d")
    )
    return value.strftime(py_format)


def build_query_params(extraction: Any, runtime_values: dict[str, Any]) -> dict[str, Any]:
    params = {}
    for name, metadata in get_extra(extraction, "query_parameters", {}).items():
        value_template = metadata.get("value_template")
        if isinstance(value_template, str):
            params[name] = coerce_query_value(
                substitute(value_template, runtime_values),
                metadata.get("type"),
            )
        else:
            params[name] = coerce_query_value(value_template, metadata.get("type"))
        if metadata.get("required") and params[name] in {None, ""}:
            raise ValueError(f"Required API query parameter is empty: {name}")
    return params


def coerce_query_value(value: Any, parameter_type: str | None) -> Any:
    if value is None:
        return None
    parameter_type = str(parameter_type or "string").lower()
    if parameter_type in {"integer", "bigint"}:
        return int(value)
    if parameter_type in {"decimal", "float"}:
        return float(value)
    if parameter_type == "boolean":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "y"}
    return value


def build_headers(source: Any) -> dict[str, str]:
    extraction = source.extraction
    auth_type = str(extraction.auth_type or "none")
    if auth_type == "none":
        return {}
    if auth_type == "api_key_header":
        header_name = get_extra(extraction, "api_key_header_name")
        if not header_name:
            raise ValueError("api_key_header auth requires api_key_header_name")
        secret = resolve_env_or_secret(
            api_key_secret_location(source),
            label=f"{header_name} API key",
        )
        return {header_name: secret}
    raise NotImplementedError(f"Unsupported API auth_type: {auth_type}")


def api_key_secret_location(source: Any) -> str:
    connection_name = str(source.extraction.connection_name or "")
    configured = get_extra(source.extraction, "api_key_secret_ref")
    if configured:
        return str(configured)
    normalized = normalize_identifier(connection_name)
    if not normalized:
        raise ValueError("api_key_header auth requires connection_name or api_key_secret_ref")
    return f"openbao:secret/data/ingestion-framework/api/{normalized}#api_key"


def payload_to_rows(
    payload: dict[str, Any], source: Any, parameter_context: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    response_shape = get_extra(source.extraction, "response_shape")
    if response_shape == "timeseries_arrays":
        return timeseries_payload_to_rows(payload, source, parameter_context or {})
    records = extract_records(payload, get_extra(source.extraction, "response_record_path", ""))
    return [record_to_schema_row(record, source) for record in records]


def extract_records(payload: dict[str, Any], record_path: str) -> list[dict[str, Any]]:
    if not record_path:
        return []
    value = get_path(payload, strip_json_path(record_path).removesuffix("[*]"))
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def record_to_schema_row(record: dict[str, Any], source: Any) -> dict[str, Any]:
    output = {}
    for column_name, column_config in source.schema.columns.items():
        source_path = get_extra(column_config, "source_json_path") or column_name
        output[column_name] = get_path(record, strip_json_path(source_path))
    if source.schema_policy.get("include_unmodeled_columns"):
        for key, value in flatten_dict(record).items():
            normalized = normalize_api_field_name(key)
            output.setdefault(normalized, value)
    return output


def timeseries_payload_to_rows(
    payload: dict[str, Any], source: Any, parameter_context: dict[str, Any]
) -> list[dict[str, Any]]:
    array_parent_path = strip_json_path(get_extra(source.extraction, "array_parent_path", "$.hourly"))
    array_parent = get_path(payload, array_parent_path) or {}
    time_values = array_parent.get("time", [])
    rows = []
    for index, time_value in enumerate(time_values):
        row = {}
        for column_name, column_config in source.schema.columns.items():
            source_path = get_extra(column_config, "source_json_path") or column_name
            row[column_name] = get_path_for_index(payload, source_path, index, time_value)
        if source.schema_policy.get("include_unmodeled_columns"):
            row.update(build_timeseries_unmodeled_fields(payload, source, index, time_value, row))
        for key, value in parameter_context.items():
            if key.startswith("_"):
                row.setdefault(key, value)
        rows.append(row)
    return rows


def get_path_for_index(
    payload: dict[str, Any], source_path: str, index: int, time_value: Any | None = None
) -> Any:
    cleaned = strip_json_path(source_path)
    if "[*]" not in cleaned:
        return get_path(payload, cleaned)
    if cleaned == "daily.time[*]" and time_value:
        return str(time_value).split("T", 1)[0]
    parent_path, leaf = cleaned.split("[*]", 1)[0].rsplit(".", 1)
    values = get_path(payload, parent_path + "." + leaf)
    if isinstance(values, list) and index < len(values):
        return values[index]
    return None


def build_timeseries_unmodeled_fields(
    payload: dict[str, Any],
    source: Any,
    index: int,
    time_value: Any,
    modeled_row: dict[str, Any],
) -> dict[str, Any]:
    normalizer = ColumnNormalizer()
    output = {}
    array_parent_path = strip_json_path(get_extra(source.extraction, "array_parent_path", "$.hourly"))
    array_parent = get_path(payload, array_parent_path) or {}
    if isinstance(array_parent, dict):
        for key, value in array_parent.items():
            if isinstance(value, list) and index < len(value):
                column_name = normalize_api_field_name(key)
                output.setdefault(column_name, value[index])

    for metadata_path in get_extra(source.extraction, "metadata_paths", []):
        value = get_path(payload, strip_json_path(metadata_path))
        column_name = normalize_api_field_name(metadata_path)
        output.setdefault(column_name, value)

    # Keep the canonical time value available even when the schema calls it tm_start.
    output.setdefault("time", time_value)
    return {key: value for key, value in output.items() if key not in modeled_row}


def resolve_path(path: str, base_dir: Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return base_dir / candidate


def substitute(value: str, runtime_values: dict[str, Any]) -> str:
    result = value
    for key, item in runtime_values.items():
        result = result.replace("{" + key + "}", str(item))
    return result


def get_extra(model: Any, key: str, default: Any = None) -> Any:
    if isinstance(model, dict):
        return model.get(key, default)
    if hasattr(model, key):
        value = getattr(model, key)
        if value is not None:
            return value
    extra = getattr(model, "model_extra", None) or {}
    return extra.get(key, default)


def strip_json_path(path: str) -> str:
    return str(path).removeprefix("$.").removeprefix("$")


def get_path(value: Any, path: str) -> Any:
    if path in {"", "."}:
        return value
    current = value
    for part in path.split("."):
        if part == "":
            continue
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def flatten_dict(value: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened = {}
    for key, item in value.items():
        name = f"{prefix}_{key}" if prefix else str(key)
        if isinstance(item, dict):
            flattened.update(flatten_dict(item, name))
        elif not isinstance(item, list):
            flattened[name] = item
    return flattened


def normalize_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_api_field_name(value: str) -> str:
    dotted = str(value).replace(".", "_")
    snake = re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", dotted)
    return ColumnNormalizer().normalize([snake])[0]
