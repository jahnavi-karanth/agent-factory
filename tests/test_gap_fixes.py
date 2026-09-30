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
    client.post(f"/projects/{project_id}/documents", files={"file": ("workflow.md", b"# Workflow", "text/markdown")}, headers=headers)
    first = client.post(f"/projects/{project_id}/workflows/requirements", json={}, headers=headers)
    second = client.post(f"/projects/{project_id}/workflows/requirements", json={}, headers=headers)
    assert first.status_code == 202
    assert first.headers["location"].endswith(first.json()["run_id"])
    assert second.status_code == 409


def test_typed_clarification_rest_fallback(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Clarifications"}, headers=headers).json()["project_id"]
    client.post(f"/projects/{project_id}/documents", files={"file": ("workflow.md", b"# Workflow", "text/markdown")}, headers=headers)
    run = client.post(f"/projects/{project_id}/workflows/requirements", json={}, headers=headers).json()
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


def test_document_search_stop_words_and_relevance_scores(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Search Test"}, headers=headers).json()["project_id"]
    client.post(f"/projects/{project_id}/documents", files={"file": ("scope.md", b"# 3. Scope\n\nThis section defines the corporate expense management project scope.", "text/markdown")}, headers=headers)
    
    # Natural language search with stop words
    res = client.get(f"/projects/{project_id}/documents/search?q=what+is+the+scope+of+the+project", headers=headers)
    assert res.status_code == 200
    hits = res.json()
    assert len(hits) > 0
    first_hit = hits[0]
    assert "score" in first_hit
    assert "distance" in first_hit
    assert "Scope" in first_hit["document"] or "scope" in first_hit["document"].lower()
    assert first_hit["score"] > 0.0


def test_legacy_upload_brd_removed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    res = client.post("/api/brd/upload", files={"file": ("test.md", b"# Test", "text/markdown")})
    assert res.status_code == 404


def test_list_project_documents_and_cancel_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Cancel Test"}, headers=headers).json()["project_id"]
    client.post(f"/projects/{project_id}/documents", files={"file": ("doc.md", b"# Doc\n- REQ-1", "text/markdown")}, headers=headers)
    
    # 1. List project documents
    docs_res = client.get(f"/projects/{project_id}/documents", headers=headers)
    assert docs_res.status_code == 200
    docs = docs_res.json()
    assert len(docs) == 1
    assert docs[0]["filename"] == "doc.md"

    # 2. Start workflow run
    run_res = client.post(f"/projects/{project_id}/workflows/requirements", json={}, headers=headers)
    assert run_res.status_code == 202
    run_id = run_res.json()["run_id"]

    # 3. List runs
    runs_res = client.get(f"/projects/{project_id}/runs", headers=headers)
    assert runs_res.status_code == 200
    assert len(runs_res.json()) == 1

    # 4. Cancel workflow run
    cancel_res = client.post(f"/projects/{project_id}/runs/{run_id}/cancel", headers=headers)
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "CANCELLED"

    # 5. Starting a new run should now succeed (no 409 conflict)
    new_run = client.post(f"/projects/{project_id}/workflows/requirements", json={}, headers=headers)
    assert new_run.status_code == 202


def test_project_scoped_requirements_versions_audit(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(app_for(tmp_path / "db.sqlite3"))
    headers = auth(client)
    project_id = client.post("/projects", json={"name": "Proj Scope Test"}, headers=headers).json()["project_id"]
    client.post(f"/projects/{project_id}/documents", files={"file": ("doc.md", b"# Doc\n- REQ-1", "text/markdown")}, headers=headers)
    client.post(f"/projects/{project_id}/workflows/requirements", json={}, headers=headers)

    # Requirements
    reqs_res = client.get(f"/projects/{project_id}/requirements", headers=headers)
    assert reqs_res.status_code == 200
    assert reqs_res.json()["title"] is not None

    # Versions
    vers_res = client.get(f"/projects/{project_id}/versions", headers=headers)
    assert vers_res.status_code == 200
    assert len(vers_res.json()) >= 1

    # Audit
    audit_res = client.get(f"/projects/{project_id}/audit", headers=headers)
    assert audit_res.status_code == 200
    assert isinstance(audit_res.json(), list)


