from __future__ import annotations

import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from metadata_api.models import SourceDefinitionCreate, SourceDefinitionUpdate
from metadata_api.repository import SourceDefinitionRepository
from metadata_api.yaml_generator import to_source_yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = ROOT / "data" / "metadata" / "metadata.db"
UI_DIR = ROOT / "metadata_ui"


def get_repository() -> SourceDefinitionRepository:
    db_path = Path(os.getenv("METADATA_DB_PATH", str(DEFAULT_DB_PATH)))
    return SourceDefinitionRepository(db_path)


app = FastAPI(
    title="Ingestion Metadata Manager",
    description="Local metadata management app for ingestion source definitions.",
    version="0.1.0",
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/source-definitions")
def list_source_definitions(
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    return repo.list()


@app.post("/api/source-definitions", status_code=201)
def create_source_definition(
    request: SourceDefinitionCreate,
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    try:
        return repo.create(request.payload, request.created_by)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/source-definitions/{definition_id}")
def get_source_definition(
    definition_id: int,
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    record = repo.get(definition_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source definition not found")
    return record


@app.put("/api/source-definitions/{definition_id}")
def update_source_definition(
    definition_id: int,
    request: SourceDefinitionUpdate,
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    record = repo.update(definition_id, request.payload, request.updated_by)
    if record is None:
        raise HTTPException(status_code=404, detail="Source definition not found")
    return record


@app.delete("/api/source-definitions/{definition_id}", status_code=204)
def delete_source_definition(
    definition_id: int,
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    if not repo.delete(definition_id):
        raise HTTPException(status_code=404, detail="Source definition not found")
    return None


@app.get("/api/source-definitions/{definition_id}/yaml", response_class=PlainTextResponse)
def get_source_definition_yaml(
    definition_id: int,
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    record = repo.get(definition_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source definition not found")
    return to_source_yaml(record.definition)


@app.post("/api/source-definitions/{definition_id}/export-yaml")
def export_source_definition_yaml(
    definition_id: int,
    repo: SourceDefinitionRepository = Depends(get_repository),
):
    record = repo.get(definition_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Source definition not found")
    output_dir = ROOT / "configs" / "sources"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{record.object_id}.yaml"
    output_path.write_text(to_source_yaml(record.definition), encoding="utf-8")
    return {"path": str(output_path)}


if UI_DIR.exists():
    app.mount("/assets", StaticFiles(directory=UI_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(UI_DIR / "index.html")
