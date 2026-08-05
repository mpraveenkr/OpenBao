from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from metadata_api.normalized_database_importer import NormalizedDatabaseWorkbookImporter
from metadata_api.repository import SourceDefinitionRepository
from metadata_api.yaml_generator import to_source_yaml


DEFAULT_REPORT_DIR = Path("data/metadata/import_reports")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate source YAML files from a normalized or compact multi-object workbook."
    )
    parser.add_argument("--input", required=True, help="Normalized or compact multi-object workbook")
    parser.add_argument("--output-dir", default="configs/sources", help="Destination YAML folder")
    parser.add_argument("--metadata-db", help="Optional SQLite metadata DB for upsert")
    parser.add_argument("--dry-run", action="store_true", help="Validate/report without writing YAML or DB records")
    parser.add_argument("--limit", type=int, help="Optional max objects to process, useful for validation checks")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Folder for JSON import report")
    args = parser.parse_args()

    report = import_workbook(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


def import_workbook(args: argparse.Namespace) -> dict[str, object]:
    importer = NormalizedDatabaseWorkbookImporter()
    payloads = importer.load_all(args.input)
    if args.limit is not None:
        payloads = payloads[: args.limit]

    output_dir = Path(args.output_dir)
    report = {
        "input": args.input,
        "output_dir": str(output_dir),
        "metadata_db": args.metadata_db,
        "dry_run": args.dry_run,
        "limit": args.limit,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "objects_processed": 0,
        "yaml_generated": 0,
        "metadata_upserts": 0,
        "successes": [],
        "failures": [],
    }

    for payload in payloads:
        try:
            output_path = output_dir / f"{payload.object_id}.yaml"
            if not args.dry_run:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(to_source_yaml(payload), encoding="utf-8")
                report["yaml_generated"] += 1
                if args.metadata_db:
                    upsert_metadata(args.metadata_db, payload)
                    report["metadata_upserts"] += 1
            report["objects_processed"] += 1
            report["successes"].append(
                {
                    "object_id": payload.object_id,
                    "source_system": payload.source_system,
                    "object_name": payload.object_name,
                    "columns": len(payload.columns),
                    "output_path": str(output_path),
                }
            )
        except Exception as exc:
            report["failures"].append(
                {"object_id": payload.object_id, "error": str(exc)}
            )

    if not args.dry_run:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"normalized_database_import_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        report["report_path"] = str(report_path)

    return report


def upsert_metadata(db_path: str, payload) -> None:
    repository = SourceDefinitionRepository(db_path)
    existing = next(
        (record for record in repository.list() if record.object_id == payload.object_id),
        None,
    )
    if existing:
        repository.update(existing.id, payload, "normalized_database_import")
    else:
        repository.create(payload, "normalized_database_import")


if __name__ == "__main__":
    raise SystemExit(main())
