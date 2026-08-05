from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from ingestion_framework.core.runner import IngestionRunner


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ingest-object")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_object = subparsers.add_parser("run-object", help="Run one configured source object")
    run_object.add_argument("--config", required=True, help="Path to source object YAML")
    run_object.add_argument("--storage", required=True, help="Path to storage YAML")
    run_object.add_argument(
        "--audit-db",
        required=True,
        help=(
            "Audit/watermark store: SQLite path, Postgres SQLAlchemy URL, "
            "or env:VARIABLE_NAME"
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "run-object":
        runner = IngestionRunner(
            source_config_path=args.config,
            storage_config_path=args.storage,
            audit_db_path=args.audit_db,
            base_dir=Path.cwd(),
        )
        result = runner.run()
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0

    parser.error(f"Unsupported command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
