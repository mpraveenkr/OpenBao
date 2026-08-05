from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_airflow_dags", PROJECT_ROOT / "tools/generate_airflow_dags.py"
)
assert SPEC and SPEC.loader
generator = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generator
SPEC.loader.exec_module(generator)


def write_source(root: Path, relative_path: str, **overrides) -> Path:
    data = {
        "object_id": "customers",
        "source_system": "sample",
        "source_type": "file",
        "enabled": True,
    }
    data.update(overrides)
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_default_discovery_is_limited_to_four_ingestion_configs():
    paths = generator.discover_configs(
        PROJECT_ROOT,
        scan_all=False,
        include_all_databases=False,
        explicit_configs=[],
    )

    assert [path.relative_to(PROJECT_ROOT).as_posix() for path in paths] == sorted(
        generator.DEFAULT_SELECTED_CONFIGS
    )


def test_scan_all_excludes_compact_databases_without_explicit_gate(tmp_path):
    regular = write_source(tmp_path, "configs/sources/api.yaml")
    database = write_source(
        tmp_path,
        "configs/sources/database_compact_generated/db.yaml",
        source_type="database",
    )

    safe_paths = generator.discover_configs(
        tmp_path, scan_all=True, include_all_databases=False, explicit_configs=[]
    )
    broad_paths = generator.discover_configs(
        tmp_path, scan_all=True, include_all_databases=True, explicit_configs=[]
    )

    assert safe_paths == [regular.resolve()]
    assert broad_paths == sorted([regular.resolve(), database.resolve()])


def test_filters_use_source_metadata(tmp_path):
    api = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/weather.yaml",
            object_id="weather",
            source_system="open_meteo",
            source_type="api",
        ),
        tmp_path,
    )
    database = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/customer.yaml",
            object_id="customer",
            source_system="itron",
            source_type="database",
        ),
        tmp_path,
    )

    selected = generator.filter_sources(
        [api, database],
        source_types={"api"},
        source_systems={"open_meteo"},
        object_ids={"weather"},
        load_types=set(),
    )

    assert selected == [api]


def test_render_uses_manual_schedule_and_existing_cli(tmp_path):
    source = generator.load_metadata(
        write_source(tmp_path, "configs/sources/customers.yaml"),
        tmp_path,
    )

    rendered = generator.render_dag(
        source,
        storage="configs/storage_minio.yaml",
        audit_db="/state/audit.db",
    )

    assert "schedule=None" in rendered
    assert "max_active_runs=1" in rendered
    assert "retries=1" in rendered
    assert "retry_delay=timedelta(minutes=5)" in rendered
    assert "tags=['ingestion-framework', 'file', 'sample', 'ongoing']" in rendered
    assert (
        "ingest-object run-object --config "
        "/opt/ingestion-framework/configs/sources/customers.yaml "
        "--storage /opt/ingestion-framework/configs/storage_minio.yaml "
        "--audit-db /state/audit.db"
    ) in rendered
    compile(rendered, "generated_dag.py", "exec")


def test_render_uses_orchestration_schedule(tmp_path):
    source = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/weather.yaml",
            orchestration={"schedule": "0 6 * * *"},
        ),
        tmp_path,
    )

    assert source.orchestration.schedule == "0 6 * * *"
    assert "schedule='0 6 * * *'" in generator.render_dag(
        source, storage="storage.yaml", audit_db="/state/audit.db"
    )


def test_render_uses_orchestration_runtime_options(tmp_path):
    source = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/weather.yaml",
            orchestration={
                "schedule": "0 * * * *",
                "start_date": "2026-01-01",
                "catchup": True,
                "retries": 3,
                "retry_delay_minutes": 10,
                "max_active_runs": 2,
                "pool": "api_pool",
                "priority_weight": 7,
                "tags": ["bronze", "weather"],
            },
        ),
        tmp_path,
    )

    rendered = generator.render_dag(source, storage="storage.yaml", audit_db="/state/audit.db")

    assert "start_date=datetime(2026, 1, 1)" in rendered
    assert "catchup=True" in rendered
    assert "max_active_runs=2" in rendered
    assert "retries=3" in rendered
    assert "retry_delay=timedelta(minutes=10)" in rendered
    assert "pool='api_pool'" in rendered
    assert "priority_weight=7" in rendered
    assert "tags=['ingestion-framework', 'file', 'sample', 'ongoing', 'bronze', 'weather']" in rendered
    compile(rendered, "generated_dag.py", "exec")


def test_lawson_full_loads_infer_one_time_and_can_be_filtered(tmp_path):
    lawson = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/database_compact_generated/lawson.yaml",
            object_id="lawson_erp_apvenmast",
            source_system="lawson_erp",
            source_type="database",
            load_strategy="full",
        ),
        tmp_path,
    )
    ongoing = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/database_compact_generated/meter.yaml",
            object_id="meter_reads",
            source_system="ami",
            source_type="database",
            load_strategy="incremental",
        ),
        tmp_path,
    )

    assert lawson.orchestration.load_type == "one_time"
    assert "tags=['ingestion-framework', 'database', 'lawson_erp', 'one_time']" in generator.render_dag(
        lawson, storage="storage.yaml", audit_db="/state/audit.db"
    )
    assert generator.filter_sources(
        [lawson, ongoing],
        source_types=set(),
        source_systems=set(),
        object_ids=set(),
        load_types={"ongoing"},
    ) == [ongoing]


def test_explicit_orchestration_load_type_overrides_lawson_inference(tmp_path):
    source = generator.load_metadata(
        write_source(
            tmp_path,
            "configs/sources/database_compact_generated/lawson.yaml",
            object_id="lawson_erp_daily_table",
            source_system="lawson_erp",
            source_type="database",
            load_strategy="full",
            orchestration={"load_type": "ongoing", "schedule": "30 5 * * *"},
        ),
        tmp_path,
    )

    assert source.orchestration.load_type == "ongoing"
    assert source.orchestration.schedule == "30 5 * * *"


def test_one_time_load_rejects_recurring_schedule(tmp_path):
    with pytest.raises(ValueError, match="one_time objects must use manual scheduling or @once"):
        generator.load_metadata(
            write_source(
                tmp_path,
                "configs/sources/lawson.yaml",
                object_id="lawson_erp_apvenmast",
                source_system="lawson_erp",
                source_type="database",
                load_strategy="full",
                orchestration={"schedule": "0 5 * * *"},
            ),
            tmp_path,
        )


def test_duplicate_dag_names_are_rejected(tmp_path):
    first = generator.load_metadata(
        write_source(tmp_path, "configs/sources/one.yaml"), tmp_path
    )
    second = generator.load_metadata(
        write_source(tmp_path, "configs/sources/two.yaml"), tmp_path
    )

    with pytest.raises(ValueError, match="Duplicate generated DAG filename"):
        generator.generate(
            [first, second],
            tmp_path / "dags",
            storage="storage.yaml",
            audit_db="/state/audit.db",
        )


def test_generate_uses_container_project_root_override(tmp_path):
    source = generator.load_metadata(
        write_source(tmp_path, "configs/sources/customers.yaml"),
        tmp_path,
    )

    generated = generator.generate(
        [source],
        tmp_path / "dags",
        storage="storage.yaml",
        audit_db="data/audit.db",
        container_project_root="/runtime/project",
    )

    rendered = generated[0].read_text(encoding="utf-8")
    assert "--config /runtime/project/configs/sources/customers.yaml" in rendered
    assert "--storage /runtime/project/storage.yaml" in rendered


def test_validate_generated_dags_compiles_python(tmp_path):
    source = generator.load_metadata(
        write_source(tmp_path, "configs/sources/customers.yaml"),
        tmp_path,
    )
    generated = generator.generate(
        [source],
        tmp_path / "dags",
        storage="storage.yaml",
        audit_db="/state/audit.db",
    )

    assert generator.validate_generated_dags(generated) == generated
