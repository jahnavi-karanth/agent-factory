from fastapi.testclient import TestClient

from app.analyzer import RequirementsAnalyzer
from app.main import create_app
from app.repository import SQLiteRepository
from app.service import IngestionService

from tests.test_persistence import FakeAnalysisExtractor, FakeExtractor, make_app


from app.parser import parse_document


def test_hitl_websocket_persists_answers_and_resolved_model(tmp_path):
    db_path = tmp_path / "hitl.sqlite3"
    repository = SQLiteRepository(str(db_path))
    service = IngestionService(FakeExtractor())
    analyzer = RequirementsAnalyzer(FakeAnalysisExtractor())
    app = create_app(service=service, analyzer=analyzer, repository=repository)
    client = TestClient(app)
    
    doc = parse_document("hitl.md", b"# HITL")
    model = service.ingest(doc)
    repository.save_requirements_model(model, doc.text, "text")
    brd_id = model.brd_id

    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()
    assert analysis["quality_status"] == "READY_FOR_CLARIFICATION"
    session_response = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]})
    assert session_response.status_code == 200
    session_id = session_response.json()["session_id"]
    with client.websocket_connect(f"/ws/hitl/{session_id}") as websocket:
        assert websocket.receive_json()["type"] == "resumed"
        question = websocket.receive_json()
        assert question["type"] == "question"
        websocket.send_json({"type": "answer", "question_id": "Q-001", "answer": "Submitted status values are Draft and Submitted."})
        assert websocket.receive_json()["type"] == "answer_acknowledged"
        assert websocket.receive_json()["type"] == "completed"
    state = client.get(f"/api/hitl/session/{session_id}").json()
    assert state["status"] == "COMPLETED"
    assert state["answers"][0]["question_id"] == "Q-001"
    db = __import__("sqlite3").connect(db_path)
    actions = {row[0] for row in db.execute("select action from audit_logs")}
    assert "HITL_SESSION_CREATED" in actions
    assert "HITL_ANSWER_RECORDED" in actions
    assert "RESOLVED_REQUIREMENTS_CREATED" in actions
    assert db.execute("select count(*) from resolved_requirements_models").fetchone()[0] == 1


def test_hitl_rejects_analysis_without_questions(tmp_path):
    class ClearAnalysis:
        def generate_json(self, prompt, schema):
            return {"issues": [], "clarification_questions": []}
    repository = SQLiteRepository(str(tmp_path / "clear.sqlite3"))
    service = IngestionService(FakeExtractor())
    app = create_app(service=service, analyzer=RequirementsAnalyzer(ClearAnalysis()), repository=repository)
    client = TestClient(app)
    doc = parse_document("clear.md", b"# Clear")
    model = service.ingest(doc)
    repository.save_requirements_model(model, doc.text, "text")
    brd_id = model.brd_id

    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()
    response = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]})
    assert response.status_code == 409

