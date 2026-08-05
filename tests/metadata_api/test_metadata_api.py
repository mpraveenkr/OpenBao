from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from metadata_api.app import app, get_repository
from metadata_api.repository import SourceDefinitionRepository
from tests.metadata_api.test_yaml_generator import sample_payload


def test_metadata_api_create_list_yaml_and_export(tmp_path):
    repo = SourceDefinitionRepository(tmp_path / "metadata.db")

    def override_repo():
        return repo

    app.dependency_overrides[get_repository] = override_repo
    client = TestClient(app)
    try:
        response = client.post(
            "/api/source-definitions",
            json={"payload": sample_payload().model_dump(mode="json"), "created_by": "pytest"},
        )
        assert response.status_code == 201
        definition_id = response.json()["id"]

        list_response = client.get("/api/source-definitions")
        assert list_response.status_code == 200
        assert len(list_response.json()) == 1

        yaml_response = client.get(f"/api/source-definitions/{definition_id}/yaml")
        assert yaml_response.status_code == 200
        assert "object_id: sample_csv_customers_ui" in yaml_response.text

        export_response = client.post(f"/api/source-definitions/{definition_id}/export-yaml")
        assert export_response.status_code == 200
        exported_path = Path(export_response.json()["path"])
        assert exported_path.exists()
    finally:
        exported = Path("configs/sources/sample_csv_customers_ui.yaml")
        if exported.exists():
            exported.unlink()
        app.dependency_overrides.clear()
