from pathlib import Path

from fastapi.testclient import TestClient

from app.analyzer import RequirementsAnalyzer
from app.main import create_app
from app.repository import SQLiteRepository
from app.service import IngestionService
from tests.test_persistence import FakeAnalysisExtractor, FakeExtractor


def make_workflow_app(path: Path):
    repository = SQLiteRepository(str(path))
    return create_app(
        service=IngestionService(FakeExtractor()),
        analyzer=RequirementsAnalyzer(FakeAnalysisExtractor()),
        repository=repository,
    )


def test_project_run_langgraph_interrupt_resume_approval_and_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = TestClient(make_workflow_app(tmp_path / "workflow.sqlite3"))
    registration = client.post("/auth/register", json={"email": "owner@example.com", "password": "correct horse battery staple"})
    assert registration.status_code == 201
    headers = {"Authorization": f"Bearer {registration.json()['access_token']}"}
    project = client.post("/projects", json={"name": "Requirements Project"}, headers=headers)
    assert project.status_code == 201
    project_id = project.json()["project_id"]

    upload = client.post("/api/brd/upload", files={"file": ("workflow.md", b"# Workflow", "text/markdown")})
    assert upload.status_code == 200
    brd_id = upload.json()["brd_id"]

    started = client.post(f"/projects/{project_id}/workflows/requirements", json={"brd_id": brd_id}, headers=headers)
    assert started.status_code == 202
    run_id = started.json()["run_id"]
    assert started.json()["status"] == "PAUSED"
    assert "clarification_request" in str(started.json()["interrupt"])

    resumed = client.post(f"/projects/{project_id}/runs/{run_id}/hitl/response", json={"payload": [{"question_id": "Q-001", "answer": "Draft and Submitted statuses are supported."}]}, headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "PAUSED"
    assert "approval_request" in str(resumed.json()["interrupt"])

    approved = client.post(f"/projects/{project_id}/runs/{run_id}/approval", json={"payload": {"decision": "APPROVE"}}, headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "COMPLETED"

    run = client.get(f"/projects/{project_id}/runs/{run_id}", headers=headers)
    assert run.json()["status"] == "COMPLETED"
    artifacts = client.get(f"/projects/{project_id}/runs/{run_id}/artifacts", headers=headers)
    assert artifacts.status_code == 200
    assert Path(artifacts.json()["markdown_path"]).exists()
    assert Path(artifacts.json()["json_path"]).exists()
    events = client.get(f"/projects/{project_id}/runs/{run_id}/events", headers=headers)
    assert events.status_code == 200
    assert "workflow_started" in events.text


def test_project_routes_require_authentication(tmp_path):
    client = TestClient(make_workflow_app(tmp_path / "auth.sqlite3"))
    assert client.post("/projects", json={"name": "No Access"}).status_code == 401
