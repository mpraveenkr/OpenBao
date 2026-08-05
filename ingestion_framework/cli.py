from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from ingestion_framework.config.loader import ConfigLoader
from ingestion_framework.core.runner import IngestionRunner
from ingestion_framework.secrets.preflight import check_requirements, collect_requirements


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

    check_secrets = subparsers.add_parser(
        "check-secrets",
        help="Resolve every secret a config needs, without printing any values",
    )
    check_secrets.add_argument("--config", help="Path to source object YAML")
    check_secrets.add_argument("--storage", help="Path to storage YAML")
    check_secrets.add_argument(
        "--audit-db",
        help="Audit/watermark store reference to resolve, such as env:INGESTION_AUDIT_DB_URL",
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

    if args.command == "check-secrets":
        return run_check_secrets(args, parser)

    parser.error(f"Unsupported command: {args.command}")
    return 2


def run_check_secrets(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if not any([args.config, args.storage, args.audit_db]):
        parser.error("check-secrets needs at least one of --config, --storage, or --audit-db")

    loader = ConfigLoader()
    source = loader.load_source(args.config) if args.config else None

    storage = None
    if args.storage:
        registry = loader.load_storage(args.storage)
        if source is not None:
            storage_name = source.target.storage_name
            if storage_name not in registry.storages:
                print(f"Target storage is not defined in storage config: {storage_name}")
                return 1
            storage = registry.storages[storage_name]
        elif len(registry.storages) == 1:
            storage = next(iter(registry.storages.values()))
        else:
            parser.error("--storage defines multiple storages; pass --config to select one")

    requirements = collect_requirements(source, storage, args.audit_db)
    if not requirements:
        print("No secret references found for this configuration.")
        return 0

    checks = check_requirements(requirements)
    width = max(len(check.label) for check in checks)
    for check in checks:
        status = "OK  " if check.ok else "FAIL"
        print(f"{status}  {check.label.ljust(width)}  {check.location}")
        if not check.ok:
            print(f"        {check.detail}")

    failed = [check for check in checks if not check.ok]
    print()
    print(f"{len(checks) - len(failed)} of {len(checks)} secret references resolved.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
