#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DIST_DIR = PROJECT_ROOT / "dist"
OUTPUT = DIST_DIR / "create_ingestion_framework_tree.py.txt"

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "dist",
    "ingestion_framework.egg-info",
    "deploy/single-node-airflow/generated",
}
EXCLUDED_FILES = {
    ".DS_Store",
    ".env",
    "deploy/single-node-airflow/.env",
}
EXCLUDED_SUFFIXES = {
    ".pyc",
}


def is_excluded(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT).as_posix()
    if path.name in EXCLUDED_FILES or relative in EXCLUDED_FILES:
        return True
    if path.suffix in EXCLUDED_SUFFIXES:
        return True
    parts = relative.split("/")
    for index in range(len(parts)):
        candidate = "/".join(parts[: index + 1])
        if candidate in EXCLUDED_DIRS or parts[index] in EXCLUDED_DIRS:
            return True
    if relative.startswith("data/audit/") and path.suffix == ".db":
        return True
    if relative.startswith("data/metadata/") and path.suffix == ".db":
        return True
    if relative.startswith("data/output/"):
        return True
    return False


def build_manifest() -> dict[str, str]:
    manifest: dict[str, str] = {}
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if not path.is_file() or is_excluded(path):
            continue
        relative = path.relative_to(PROJECT_ROOT).as_posix()
        manifest[relative] = base64.b64encode(path.read_bytes()).decode("ascii")
    return manifest


def main() -> int:
    DIST_DIR.mkdir(exist_ok=True)
    manifest_json = json.dumps(build_manifest(), indent=2, sort_keys=True)
    script = f'''#!/usr/bin/env python3
from __future__ import annotations

import base64
from pathlib import Path


TARGET_ROOT = Path("ingestion-framework")
FILES = {manifest_json}


def main() -> int:
    TARGET_ROOT.mkdir(parents=True, exist_ok=True)
    for relative_path, encoded_content in FILES.items():
        target = TARGET_ROOT / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(encoded_content))
    print(f"Created {{TARGET_ROOT.resolve()}} with {{len(FILES)}} files.")
    print("Next:")
    print(f"  cd {{TARGET_ROOT}}/deploy/single-node-airflow")
    print("  python3 install_platform.py")
    print("  docker compose --env-file .env up -d --build")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
    OUTPUT.write_text(script)
    print(f"Wrote {OUTPUT}")
    print(f"Size: {OUTPUT.stat().st_size / 1024:.1f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
