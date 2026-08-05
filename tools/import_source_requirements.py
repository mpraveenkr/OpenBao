from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from metadata_api.excel_importer import RequirementsWorkbookImporter
from metadata_api.repository import SourceDefinitionRepository
from metadata_api.yaml_generator import to_source_yaml


DEFAULT_REPORT_DIR = Path("data/metadata/import_reports")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an ingestion source YAML config from a completed Excel workbook."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Completed requirements workbook")
    input_group.add_argument("--input-folder", help="Folder containing completed workbooks")
    parser.add_argument("--output", help="Destination YAML file for single-workbook mode")
    parser.add_argument("--output-dir", default="configs/sources", help="Destination folder for batch YAML files")
    parser.add_argument("--sheet", help="Workbook sheet name; defaults to first non-validation sheet")
    parser.add_argument("--metadata-db", help="Optional SQLite metadata DB for upsert")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report without writing YAML or DB records")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Folder for batch JSON import reports")
    args = parser.parse_args()

    if args.input:
        if not args.output:
            parser.error("--output is required with --input")
        output = import_single(args)
        print(output)
        return 0

    report = import_folder(args)
    print(json.dumps(report, indent=2, sort_keys=True))
    if report["failures"]:
        return 1
    return 0


def import_single(args: argparse.Namespace) -> Path:
    importer = RequirementsWorkbookImporter()
    payload = importer.load(args.input, args.sheet)
    output = Path(args.output)
    if not args.dry_run:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(to_source_yaml(payload), encoding="utf-8")
        if args.metadata_db:
            upsert_metadata(args.metadata_db, payload, "excel_import")
    return output


def import_folder(args: argparse.Namespace) -> dict[str, object]:
    importer = RequirementsWorkbookImporter()
    input_folder = Path(args.input_folder)
    output_dir = Path(args.output_dir)
    report = {
        "input_folder": str(input_folder),
        "output_dir": str(output_dir),
        "metadata_db": args.metadata_db,
        "dry_run": args.dry_run,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files_seen": 0,
        "sheets_processed": 0,
        "yaml_generated": 0,
        "metadata_upserts": 0,
        "successes": [],
        "failures": [],
    }

    workbooks = sorted(
        path
        for path in input_folder.glob("*.xlsx")
        if not path.name.startswith("~$")
    )
    report["files_seen"] = len(workbooks)

    for workbook_path in workbooks:
        try:
            sheet_names = [args.sheet] if args.sheet else importer.list_source_sheets(workbook_path)
        except Exception as exc:
            report["failures"].append(
                failure_record(workbook_path, None, exc)
            )
            continue

        for sheet_name in sheet_names:
            try:
                payload = importer.load(workbook_path, sheet_name)
                output_path = output_dir / f"{payload.object_id}.yaml"

                if not args.dry_run:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(to_source_yaml(payload), encoding="utf-8")
                    report["yaml_generated"] += 1
                    if args.metadata_db:
                        upsert_metadata(args.metadata_db, payload, "batch_excel_import")
                        report["metadata_upserts"] += 1

                report["sheets_processed"] += 1
                report["successes"].append(
                    {
                        "workbook": str(workbook_path),
                        "sheet": sheet_name,
                        "object_id": payload.object_id,
                        "source_type": payload.source_type,
                        "output_path": str(output_path),
                        "columns": len(payload.columns),
                    }
                )
            except Exception as exc:
                report["failures"].append(
                    failure_record(workbook_path, sheet_name, exc)
                )

    if not args.dry_run:
        report_dir = Path(args.report_dir)
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"requirements_import_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
        report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
        report["report_path"] = str(report_path)

    return report


def upsert_metadata(db_path: str, payload, user: str) -> None:
    repository = SourceDefinitionRepository(db_path)
    existing = next(
        (record for record in repository.list() if record.object_id == payload.object_id),
        None,
    )
    if existing:
        repository.update(existing.id, payload, user)
    else:
        repository.create(payload, user)


def failure_record(workbook_path: Path, sheet_name: str | None, exc: Exception) -> dict[str, str | None]:
    return {
        "workbook": str(workbook_path),
        "sheet": sheet_name,
        "error": str(exc),
    }


if __name__ == "__main__":
    raise SystemExit(main())
