from pathlib import Path

from fastapi.testclient import TestClient

from app.analyzer import RequirementsAnalyzer
from app.main import create_app
from app.document_store import DocumentStore
from app.repository import SQLiteRepository
from app.service import IngestionService
from tests.test_persistence import FakeAnalysisExtractor, FakeExtractor


def app_for(path: Path):
    return create_app(
        service=IngestionService(FakeExtractor()),
        analyzer=RequirementsAnalyzer(FakeAnalysisExtractor()),
        repository=SQLiteRepository(str(path)),
        document_store=DocumentStore(str(path.parent / "chroma")),
    )


def auth(client: TestClient):
    response = client.post("/auth/register", json={"email": "gap@example.com", "password": "password123"})
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_project_document_upload_is_idempotent_by_content_hash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Idempotency"}, headers=headers).json()["project_id"]
    payload = {"file": ("requirements.md", b"# Requirements\n\nThe system shall accept requests.", "text/markdown")}
    first = client.post(f"/projects/{project_id}/documents", files=payload, headers=headers)
    second = client.post(f"/projects/{project_id}/documents", files=payload, headers=headers)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["document_id"] == first.json()["document_id"]


def test_healthz_reports_dependencies(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert set(response.json()["checks"]) == {"sqlite", "chromadb", "filesystem"}


def test_workflow_location_and_active_run_conflict(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Workflow"}, headers=headers).json()["project_id"]
    brd = client.post("/api/brd/upload", files={"file": ("workflow.md", b"# Workflow", "text/markdown")})
    brd_id = brd.json()["brd_id"]
    first = client.post(f"/projects/{project_id}/workflows/requirements", json={"brd_id": brd_id}, headers=headers)
    second = client.post(f"/projects/{project_id}/workflows/requirements", json={"brd_id": brd_id}, headers=headers)
    assert first.status_code == 202
    assert first.headers["location"].endswith(first.json()["run_id"])
    assert second.status_code == 409


def test_typed_clarification_rest_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Clarifications"}, headers=headers).json()["project_id"]
    brd = client.post("/api/brd/upload", files={"file": ("workflow.md", b"# Workflow", "text/markdown")})
    run = client.post(f"/projects/{project_id}/workflows/requirements", json={"brd_id": brd.json()["brd_id"]}, headers=headers).json()
    response = client.post(
        f"/projects/{project_id}/runs/{run['run_id']}/clarifications",
        json={"payload": {"type": "clarification_response", "request_id": "ignored", "answers": [{"id": "Q-001", "answer": "Human answer"}]}},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "PAUSED"


def test_start_requirements_workflow_with_document_ids(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "DocIDs Workflow"}, headers=headers).json()["project_id"]
    upload_res = client.post(f"/projects/{project_id}/documents", files={"file": ("requirements.md", b"# Requirements\n\nThe system shall accept requests.", "text/markdown")}, headers=headers)
    doc_id = upload_res.json()["document_id"]
    
    # Start workflow using document_ids instead of brd_id
    run_res = client.post(f"/projects/{project_id}/workflows/requirements", json={"document_ids": [doc_id]}, headers=headers)
    assert run_res.status_code == 202
    data = run_res.json()
    assert "run_id" in data
    assert data["status"] in ("PAUSED", "COMPLETED")
