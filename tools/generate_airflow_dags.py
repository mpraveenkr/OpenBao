#!/usr/bin/env python3
"""Generate one Airflow DAG per selected ingestion source object."""

from __future__ import annotations

import argparse
import json
import py_compile
import re
import shlex
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "deploy/single-node-airflow/dags/generated"
DEFAULT_STORAGE = "configs/storage_minio.yaml"
DEFAULT_AUDIT_DB = "env:INGESTION_AUDIT_DB_URL"
CONTAINER_PROJECT_ROOT = "/opt/ingestion-framework"

DEFAULT_SELECTED_CONFIGS = (
    "configs/sources/sample_csv_customers.yaml",
    "configs/sources/api_generated/weather_forecast.yaml",
    "configs/sources/api_generated/weather_archive.yaml",
    "configs/sources/database_compact_generated/itron_mv90_cmmastst_customer_master.yaml",
)
DATABASE_CONFIG_DIR = Path("configs/sources/database_compact_generated")
DEFAULT_START_DATE = "2024-01-01"

LoadType = Literal["ongoing", "one_time"]


@dataclass(frozen=True)
class DeploymentProfile:
    container_project_root: str
    storage: str
    audit_db: str


DEPLOYMENT_PROFILES = {
    "single-node-airflow": DeploymentProfile(
        container_project_root=CONTAINER_PROJECT_ROOT,
        storage=DEFAULT_STORAGE,
        audit_db=DEFAULT_AUDIT_DB,
    ),
    "local": DeploymentProfile(
        container_project_root=str(PROJECT_ROOT),
        storage="configs/storage.yaml",
        audit_db="data/audit/ingestion_audit.db",
    ),
}


@dataclass(frozen=True)
class OrchestrationMetadata:
    load_type: LoadType
    schedule: str | None
    start_date: str
    catchup: bool
    retries: int
    retry_delay_minutes: int
    max_active_runs: int
    pool: str | None
    priority_weight: int | None
    tags: tuple[str, ...]
    notes: str | None


@dataclass(frozen=True)
class SourceMetadata:
    path: Path
    relative_path: Path
    object_id: str
    source_system: str
    source_type: str
    enabled: bool
    load_strategy: str
    orchestration: OrchestrationMetadata


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_]+", "_", value).strip("_").lower()
    if not slug:
        raise ValueError(f"Cannot create an Airflow identifier from {value!r}")
    if slug[0].isdigit():
        slug = f"object_{slug}"
    return slug


def _schedule(orchestration: dict[str, Any]) -> str | None:
    value = next(
        (
            orchestration[key]
            for key in ("schedule", "cron", "schedule_interval")
            if orchestration.get(key) not in (None, "")
        ),
        None,
    )
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in {"manual", "none", "null"}:
        return None
    return text


def _orchestration(data: dict[str, Any]) -> OrchestrationMetadata:
    orchestration = data.get("orchestration")
    if not isinstance(orchestration, dict):
        orchestration = {}

    load_type = _load_type(data, orchestration)
    schedule = _schedule(orchestration)
    if load_type == "one_time" and schedule not in {None, "@once"}:
        raise ValueError(
            f"{data.get('object_id')}: one_time objects must use manual scheduling or @once, got {schedule!r}"
        )

    return OrchestrationMetadata(
        load_type=load_type,
        schedule=schedule,
        start_date=_start_date(orchestration),
        catchup=_bool_value(orchestration.get("catchup"), default=False),
        retries=_int_value(orchestration.get("retries"), default=1, minimum=0),
        retry_delay_minutes=_int_value(
            orchestration.get("retry_delay_minutes", orchestration.get("retry_delay")),
            default=5,
            minimum=0,
        ),
        max_active_runs=_int_value(
            orchestration.get("max_active_runs"),
            default=1,
            minimum=1,
        ),
        pool=_optional_text(orchestration.get("pool")),
        priority_weight=(
            None
            if orchestration.get("priority_weight") in (None, "")
            else _int_value(orchestration.get("priority_weight"), default=1, minimum=1)
        ),
        tags=_tags(orchestration.get("tags")),
        notes=_optional_text(orchestration.get("notes")),
    )


def _load_type(data: dict[str, Any], orchestration: dict[str, Any]) -> LoadType:
    raw = next(
        (
            orchestration[key]
            for key in ("load_type", "run_type", "frequency", "schedule_hint")
            if orchestration.get(key) not in (None, "")
        ),
        None,
    )
    if raw is not None:
        normalized = str(raw).strip().lower().replace("-", "_")
        if normalized in {"one_time", "once", "oneoff", "one_off", "historical_full"}:
            return "one_time"
        if normalized in {"ongoing", "recurring", "scheduled", "continuous"}:
            return "ongoing"
        if normalized in {"manual", "none", "null"}:
            return _infer_load_type(data)
        raise ValueError(f"{data.get('object_id')}: unsupported orchestration load_type {raw!r}")
    return _infer_load_type(data)


def _infer_load_type(data: dict[str, Any]) -> LoadType:
    source_system = str(data.get("source_system", "")).lower()
    object_id = str(data.get("object_id", "")).lower()
    load_strategy = str(data.get("load_strategy", "")).lower()
    if load_strategy == "full" and (
        source_system.startswith("lawson") or object_id.startswith("lawson")
    ):
        return "one_time"
    return "ongoing"


def _start_date(orchestration: dict[str, Any]) -> str:
    raw = orchestration.get("start_date") or DEFAULT_START_DATE
    text = str(raw).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid orchestration start_date: {text!r}") from exc
    return text


def _bool_value(value: Any, *, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    raise ValueError(f"Expected boolean value, got {value!r}")


def _int_value(value: Any, *, default: int, minimum: int) -> int:
    if value in (None, ""):
        return default
    number = int(value)
    if number < minimum:
        raise ValueError(f"Expected integer >= {minimum}, got {value!r}")
    return number


def _optional_text(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value).strip()


def _tags(value: Any) -> tuple[str, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        return tuple(tag.strip() for tag in value.split(",") if tag.strip())
    if isinstance(value, list):
        return tuple(str(tag).strip() for tag in value if str(tag).strip())
    raise ValueError(f"Expected orchestration tags as list or comma-separated string, got {value!r}")


def load_metadata(path: Path, project_root: Path = PROJECT_ROOT) -> SourceMetadata:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path}: source YAML must contain a mapping")
    required = ("object_id", "source_system", "source_type")
    missing = [key for key in required if not data.get(key)]
    if missing:
        raise ValueError(f"{path}: missing required metadata: {', '.join(missing)}")
    try:
        relative_path = path.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"{path}: config must be inside project root {project_root}") from exc
    return SourceMetadata(
        path=path,
        relative_path=relative_path,
        object_id=str(data["object_id"]),
        source_system=str(data["source_system"]),
        source_type=str(data["source_type"]),
        enabled=bool(data.get("enabled", True)),
        load_strategy=str(data.get("load_strategy", "")),
        orchestration=_orchestration(data),
    )


def discover_configs(
    project_root: Path,
    *,
    scan_all: bool,
    include_all_databases: bool,
    explicit_configs: Iterable[str],
) -> list[Path]:
    explicit = list(explicit_configs)
    if explicit:
        paths = [(project_root / item).resolve() for item in explicit]
    elif scan_all:
        source_root = project_root / "configs/sources"
        paths = []
        for path in source_root.rglob("*.yaml"):
            relative = path.relative_to(project_root)
            if (
                DATABASE_CONFIG_DIR in relative.parents
                and not include_all_databases
            ):
                continue
            paths.append(path.resolve())
    else:
        paths = [(project_root / item).resolve() for item in DEFAULT_SELECTED_CONFIGS]
    missing = [str(path) for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("Source config not found: " + ", ".join(missing))
    return sorted(set(paths))


def filter_sources(
    sources: Iterable[SourceMetadata],
    *,
    source_types: set[str],
    source_systems: set[str],
    object_ids: set[str],
    load_types: set[str],
) -> list[SourceMetadata]:
    return [
        source
        for source in sources
        if (not source_types or source.source_type in source_types)
        and (not source_systems or source.source_system in source_systems)
        and (not object_ids or source.object_id in object_ids)
        and (not load_types or source.orchestration.load_type in load_types)
    ]


def _datetime_literal(iso_date: str) -> str:
    year, month, day = (int(part) for part in iso_date.split("-"))
    return f"datetime({year}, {month}, {day})"


def render_dag(
    source: SourceMetadata,
    *,
    storage: str,
    audit_db: str,
    container_project_root: str = CONTAINER_PROJECT_ROOT,
) -> str:
    dag_id = f"ingest_{_slug(source.source_system)}_{_slug(source.object_id)}"
    config_path = f"{container_project_root}/{source.relative_path.as_posix()}"
    storage_path = storage if storage.startswith("/") else f"{container_project_root}/{storage}"
    orchestration = source.orchestration
    command = " ".join(
        shlex.quote(part)
        for part in (
            "ingest-object",
            "run-object",
            "--config",
            config_path,
            "--storage",
            storage_path,
            "--audit-db",
            audit_db,
        )
    )
    schedule = repr(orchestration.schedule)
    tags = repr(
        [
            "ingestion-framework",
            source.source_type,
            source.source_system,
            orchestration.load_type,
            *orchestration.tags,
        ]
    )
    task_options = [
        f"        retries={orchestration.retries},",
        f"        retry_delay=timedelta(minutes={orchestration.retry_delay_minutes}),",
    ]
    if orchestration.pool:
        task_options.append(f"        pool={orchestration.pool!r},")
    if orchestration.priority_weight is not None:
        task_options.append(f"        priority_weight={orchestration.priority_weight},")
    task_options_text = "\n".join(task_options)
    notes = f"\n# Notes: {orchestration.notes}\n" if orchestration.notes else ""
    return f'''"""Generated from {source.relative_path.as_posix()}; do not edit by hand."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

{notes}
with DAG(
    dag_id={dag_id!r},
    description={f"Ingest {source.object_id} from {source.source_system}."!r},
    schedule={schedule},
    start_date={_datetime_literal(orchestration.start_date)},
    catchup={orchestration.catchup!r},
    max_active_runs={orchestration.max_active_runs},
    tags={tags},
) as dag:
    run_ingestion = BashOperator(
        task_id="run_ingestion",
        bash_command={command!r},
        append_env=True,
{task_options_text}
    )
'''


def generate(
    sources: Iterable[SourceMetadata],
    output_dir: Path,
    *,
    storage: str,
    audit_db: str,
    container_project_root: str = CONTAINER_PROJECT_ROOT,
) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[Path] = []
    expected_names: set[str] = set()
    for source in sources:
        filename = f"ingest_{_slug(source.source_system)}_{_slug(source.object_id)}.py"
        if filename in expected_names:
            raise ValueError(f"Duplicate generated DAG filename: {filename}")
        expected_names.add(filename)
        target = output_dir / filename
        target.write_text(
            render_dag(
                source,
                storage=storage,
                audit_db=audit_db,
                container_project_root=container_project_root,
            ),
            encoding="utf-8",
        )
        generated.append(target)
    for stale in output_dir.glob("ingest_*.py"):
        if stale.name not in expected_names:
            stale.unlink()
    return generated


def validate_generated_dags(paths: Iterable[Path]) -> list[Path]:
    validated: list[Path] = []
    for path in paths:
        py_compile.compile(str(path), doraise=True)
        validated.append(path)
    return validated


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--profile",
        choices=sorted(DEPLOYMENT_PROFILES),
        default="single-node-airflow",
        help="Deployment profile for generated runtime paths.",
    )
    parser.add_argument(
        "--container-project-root",
        help="Override the profile's project root path used inside the Airflow runtime.",
    )
    parser.add_argument("--config", action="append", default=[], help="Explicit source YAML, relative to project root.")
    parser.add_argument("--scan-all", action="store_true", help="Scan all non-database source YAML files.")
    parser.add_argument(
        "--include-all-databases",
        action="store_true",
        help="With --scan-all, explicitly include every compact database YAML.",
    )
    parser.add_argument("--source-type", action="append", default=[])
    parser.add_argument("--source-system", action="append", default=[])
    parser.add_argument("--object-id", action="append", default=[])
    parser.add_argument(
        "--load-type",
        action="append",
        choices=["ongoing", "one_time"],
        default=[],
        help="Filter by orchestration load type. Lawson full loads infer as one_time.",
    )
    parser.add_argument("--storage", help="Override the profile's storage config path.")
    parser.add_argument("--audit-db", help="Override the profile's audit/watermark backend.")
    parser.add_argument("--include-disabled", action="store_true")
    parser.add_argument("--validate", action="store_true", help="Compile generated DAG files before exiting.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.include_all_databases and not args.scan_all:
        raise SystemExit("--include-all-databases requires --scan-all")
    project_root = args.project_root.resolve()
    paths = discover_configs(
        project_root,
        scan_all=args.scan_all,
        include_all_databases=args.include_all_databases,
        explicit_configs=args.config,
    )
    sources = filter_sources(
        (load_metadata(path, project_root) for path in paths),
        source_types=set(args.source_type),
        source_systems=set(args.source_system),
        object_ids=set(args.object_id),
        load_types=set(args.load_type),
    )
    if not args.include_disabled:
        sources = [source for source in sources if source.enabled]
    output_dir = args.output_dir
    if not output_dir.is_absolute():
        output_dir = project_root / output_dir
    profile = DEPLOYMENT_PROFILES[args.profile]
    container_project_root = args.container_project_root or profile.container_project_root
    storage = args.storage or profile.storage
    audit_db = args.audit_db or profile.audit_db
    generated = generate(
        sources,
        output_dir,
        storage=storage,
        audit_db=audit_db,
        container_project_root=container_project_root,
    )
    validated = validate_generated_dags(generated) if args.validate else []
    print(
        json.dumps(
            {
                "count": len(generated),
                "profile": args.profile,
                "validated": len(validated),
                "generated": [str(path) for path in generated],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
