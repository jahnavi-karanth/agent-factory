from pathlib import Path

from fastapi.testclient import TestClient

from app.analyzer import RequirementsAnalyzer
from app.main import create_app
from app.repository import SQLiteRepository
from app.service import IngestionService


class FakeExtractor:
    def extract(self, document):
        return {
            "title": "Persisted Platform",
            "business_problem": "The current process is manual.",
            "business_objectives": [],
            "stakeholders": ["Users"],
            "user_roles": ["Requester"],
            "requirements": [
                {"id": "REQ-001", "type": "functional", "description": "Users can submit requests.", "source": {"title": "2. Requests"}, "priority": None},
                {"id": "REQ-002", "type": "functional", "description": "Users can view request status.", "source": {"title": "3. Status"}, "priority": None},
            ],
            "non_functional_requirements": [], "business_rules": [], "constraints": [], "assumptions": [],
            "data_requirements": [], "external_dependencies": [], "success_criteria": [],
        }


class FakeAnalysisExtractor:
    def generate_json(self, prompt, schema):
        return {
            "issues": [{
                "issue_id": "GAP-001", "type": "gap", "severity": "HIGH", "title": "Missing status definition",
                "description": "Status behavior is incomplete.", "affected_requirements": ["REQ-002"],
                "reason": "The workflow needs a defined status behavior.", "clarification_required": True,
                "severity_reason": "It affects workflow implementation.",
            }],
            "clarification_questions": [{
                "question_id": "Q-001", "issue_id": "GAP-001", "affected_requirements": ["REQ-002"],
                "question": "What statuses should be available?", "reason": "Status behavior is incomplete.", "priority": "HIGH",
            }],
        }


def make_app(path: Path):
    repository = SQLiteRepository(str(path))
    return create_app(
        service=IngestionService(FakeExtractor()),
        analyzer=RequirementsAnalyzer(FakeAnalysisExtractor()),
        repository=repository,
    )


def test_upload_persists_brd_model_and_requirements(tmp_path):
    app = make_app(tmp_path / "artifacts.sqlite3")
    response = TestClient(app).post("/api/brd/upload", files={"file": ("persisted.md", b"# Persisted\n## 2. Requests\n## 3. Status", "text/markdown")})
    assert response.status_code == 200
    body = response.json()
    brd_id = body["brd_id"]
    retrieved = TestClient(app).get(f"/api/brd/{brd_id}/requirements")
    assert retrieved.status_code == 200
    assert [item["id"] for item in retrieved.json()["requirements"]] == ["REQ-001", "REQ-002"]
    assert retrieved.json()["source_filename"] == "persisted.md"


def test_analysis_persists_relationships_and_dynamic_count(tmp_path):
    db_path = tmp_path / "artifacts.sqlite3"
    app = make_app(db_path)
    client = TestClient(app)
    upload = client.post("/api/brd/upload", files={"file": ("persisted.md", b"# Persisted", "text/markdown")})
    brd_id = upload.json()["brd_id"]
    response = client.post("/api/requirements/analyze", json={"brd_id": brd_id})
    assert response.status_code == 200
    analysis = response.json()
    assert analysis["summary"]["total_requirements_analyzed"] == 2
    assert analysis["issues"][0]["affected_requirements"] == ["REQ-002"]
    assert analysis["clarification_questions"][0]["issue_id"] == "GAP-001"
    restored = client.get(f"/api/analysis/{analysis['analysis_id']}")
    assert restored.status_code == 200
    assert restored.json()["summary"]["total_requirements_analyzed"] == 2
    assert restored.json()["issues"][0]["affected_requirements"] == ["REQ-002"]
    assert restored.json()["clarification_questions"][0]["question_id"] == "Q-001"


def test_artifacts_survive_repository_and_app_restart(tmp_path):
    db_path = tmp_path / "restart.sqlite3"
    first = make_app(db_path)
    first_client = TestClient(first)
    upload = first_client.post("/api/brd/upload", files={"file": ("restart.md", b"# Restart", "text/markdown")})
    brd_id = upload.json()["brd_id"]
    analysis = first_client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()

    second = make_app(db_path)
    second_client = TestClient(second)
    assert second_client.get(f"/api/brd/{brd_id}/requirements").status_code == 200
    restored = second_client.get(f"/api/analysis/{analysis['analysis_id']}")
    assert restored.status_code == 200
    assert restored.json()["brd_id"] == brd_id
    assert restored.json()["clarification_questions"][0]["question_id"] == "Q-001"


def test_missing_artifact_returns_not_found(tmp_path):
    client = TestClient(make_app(tmp_path / "missing.sqlite3"))
    assert client.get("/api/brd/BRD-MISSING/requirements").status_code == 404
    assert client.get("/api/analysis/ANALYSIS-MISSING").status_code == 404


def test_repeated_upload_preserves_versions_and_latest_retrieval(tmp_path):
    db_path = tmp_path / "versions.sqlite3"
    app = make_app(db_path)
    client = TestClient(app)
    files = {"file": ("same.md", b"# Same", "text/markdown")}
    first = client.post("/api/brd/upload", files=files).json()
    second = client.post("/api/brd/upload", files=files).json()
    assert first["brd_id"] == second["brd_id"]
    db = __import__("sqlite3").connect(db_path)
    assert db.execute("select count(*) from requirements_models where brd_id=?", (first["brd_id"],)).fetchone()[0] == 2
    assert db.execute("select count(*) from brd_versions where brd_id=?", (first["brd_id"],)).fetchone()[0] == 2
