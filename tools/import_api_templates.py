from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import yaml

from metadata_api.tabbed_api_importer import TabbedApiWorkbookImporter


DEFAULT_REPORT_DIR = Path("data/metadata/import_reports")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate source YAML files from tabbed API workbook templates."
    )
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--input", help="Single API workbook")
    input_group.add_argument("--input-folder", help="Folder containing API workbooks")
    parser.add_argument("--output", help="Destination YAML file for single-workbook mode")
    parser.add_argument("--output-dir", default="configs/sources/api_generated", help="Destination YAML folder")
    parser.add_argument("--dry-run", action="store_true", help="Validate/report without writing YAML")
    parser.add_argument("--limit", type=int, help="Optional max workbooks to process")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="Folder for JSON import reports")
    args = parser.parse_args()

    if args.input:
        if not args.output and not args.dry_run:
            parser.error("--output is required with --input unless --dry-run is set")
        report = import_single(args)
    else:
        report = import_folder(args)

    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if report["failures"] else 0


def import_single(args: argparse.Namespace) -> dict[str, object]:
    importer = TabbedApiWorkbookImporter()
    report = make_report(args.input, args.output or args.output_dir, args.dry_run, args.limit)
    try:
        config = importer.load(args.input)
        output_path = Path(args.output) if args.output else Path(args.output_dir) / f"{config['object_id']}.yaml"
        if not args.dry_run:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(to_yaml(config), encoding="utf-8")
            report["yaml_generated"] += 1
        report["objects_processed"] += 1
        report["successes"].append(success_record(args.input, output_path, config))
    except Exception as exc:
        report["failures"].append({"workbook": args.input, "error": str(exc)})
    write_report(report, args.report_dir, args.dry_run)
    return report


def import_folder(args: argparse.Namespace) -> dict[str, object]:
    importer = TabbedApiWorkbookImporter()
    input_folder = Path(args.input_folder)
    output_dir = Path(args.output_dir)
    report = make_report(str(input_folder), str(output_dir), args.dry_run, args.limit)

    workbooks = [
        path
        for path in sorted(input_folder.glob("*.xlsx"))
        if not path.name.startswith("~$")
    ]
    if args.limit is not None:
        workbooks = workbooks[: args.limit]
    report["files_seen"] = len(workbooks)

    for workbook_path in workbooks:
        try:
            config = importer.load(workbook_path)
            output_path = output_dir / f"{config['object_id']}.yaml"
            if not args.dry_run:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_text(to_yaml(config), encoding="utf-8")
                report["yaml_generated"] += 1
            report["objects_processed"] += 1
            report["successes"].append(success_record(workbook_path, output_path, config))
        except Exception as exc:
            report["failures"].append({"workbook": str(workbook_path), "error": str(exc)})

    write_report(report, args.report_dir, args.dry_run)
    return report


def make_report(input_path: str, output_path: str, dry_run: bool, limit: int | None) -> dict[str, object]:
    return {
        "input": input_path,
        "output": output_path,
        "dry_run": dry_run,
        "limit": limit,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "files_seen": 0,
        "objects_processed": 0,
        "yaml_generated": 0,
        "successes": [],
        "failures": [],
    }


def success_record(workbook_path, output_path: Path, config: dict[str, object]) -> dict[str, object]:
    schema = config.get("schema", {})
    columns = schema.get("columns", {}) if isinstance(schema, dict) else {}
    extraction = config.get("extraction", {})
    return {
        "workbook": str(workbook_path),
        "object_id": config["object_id"],
        "source_system": config["source_system"],
        "object_name": config["object_name"],
        "columns": len(columns),
        "parameter_sets": len(extraction.get("parameter_sets", [])) if isinstance(extraction, dict) else 0,
        "output_path": str(output_path),
    }


def write_report(report: dict[str, object], report_dir: str, dry_run: bool) -> None:
    if dry_run:
        return
    destination = Path(report_dir)
    destination.mkdir(parents=True, exist_ok=True)
    report_path = destination / f"api_template_import_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    report["report_path"] = str(report_path)


def to_yaml(config: dict[str, object]) -> str:
    return yaml.safe_dump(
        config,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    )


if __name__ == "__main__":
    raise SystemExit(main())
