#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = PROJECT_ROOT / "dist"
OUTPUT = DIST_DIR / "bootstrap_ingestion_single_node_plain.py.txt"

INCLUDE_PATHS = [
    ".dockerignore",
    ".gitignore",
    "README.md",
    "ARCHITECTURE.md",
    "pyproject.toml",
    "configs/storage.yaml",
    "configs/sources/itron_mv90_cmmastst_customer_master.yaml",
    "configs/sources/sample_csv_customers.yaml",
    "data/input/customers.csv",
    "deploy/single-node-airflow/Dockerfile.airflow",
    "deploy/single-node-airflow/README.md",
    "deploy/single-node-airflow/config/webserver_config.py",
    "deploy/single-node-airflow/dags/ingestion_smoke_test.py",
    "deploy/single-node-airflow/docker-compose.yml",
    "deploy/single-node-airflow/install_platform.py",
    "deploy/single-node-airflow/requirements-airflow.txt",
]

INCLUDE_DIRS = [
    "ingestion_framework",
    "metadata_api",
]


def collect_files() -> list[Path]:
    files = [PROJECT_ROOT / relative for relative in INCLUDE_PATHS]
    for directory in INCLUDE_DIRS:
        for path in sorted((PROJECT_ROOT / directory).rglob("*.py")):
            files.append(path)
    return sorted(set(files))


def main() -> int:
    DIST_DIR.mkdir(exist_ok=True)
    lines = [
        "#!/usr/bin/env python3",
        "from __future__ import annotations",
        "",
        "from pathlib import Path",
        "",
        'ROOT = Path("ingestion-framework")',
        "",
        "FILES = {",
    ]
    for path in collect_files():
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        content = path.read_text()
        lines.append(f"    {relative!r}: {content!r},")
    lines.extend(
        [
            "}",
            "",
            "",
            "def main() -> int:",
            "    ROOT.mkdir(parents=True, exist_ok=True)",
            "    for relative, content in FILES.items():",
            "        target = ROOT / relative",
            "        target.parent.mkdir(parents=True, exist_ok=True)",
            "        target.write_text(content)",
            "    print(f'Created {ROOT.resolve()} with {len(FILES)} source files.')",
            "    print('Next:')",
            "    print(f'  cd {ROOT}/deploy/single-node-airflow')",
            "    print('  python3 install_platform.py')",
            "    print('  docker compose --env-file .env up -d --build')",
            "    return 0",
            "",
            "",
            'if __name__ == "__main__":',
            "    raise SystemExit(main())",
            "",
        ]
    )
    OUTPUT.write_text("\n".join(lines))
    print(f"Wrote {OUTPUT}")
    print(f"Size: {OUTPUT.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
