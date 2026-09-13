from fastapi.testclient import TestClient

from app.analyzer import RequirementsAnalyzer
from app.main import create_app
from app.repository import SQLiteRepository
from app.service import IngestionService
from tests.test_persistence import FakeExtractor


class FollowUpExtractor:
    def __init__(self):
        self.calls = 0

    def generate_json(self, prompt, schema):
        self.calls += 1
        if self.calls == 1:
            return {
                "issues": [{"issue_id": "AMB-001", "type": "ambiguity", "severity": "MEDIUM", "title": "Missing approval detail", "description": "Approval behavior is unclear.", "affected_requirements": ["REQ-001"], "reason": "The workflow is incomplete.", "clarification_required": True, "severity_reason": "Affects business behavior."}],
                "clarification_questions": [{"question_id": "Q-001", "issue_id": "AMB-001", "affected_requirements": ["REQ-001"], "question": "Who approves the request?", "reason": "Approval actor is missing.", "priority": "MEDIUM"}],
            }
        if self.calls == 2:
            return {"questions": [{"question_id": "Q-101", "issue_id": "AMB-001", "question": "What happens when approval is rejected?", "reason": "The answer revealed a rejection ambiguity.", "priority": "MEDIUM"}]}
        return {"questions": []}


def test_follow_up_round_is_generated_and_persisted(tmp_path):
    extractor = FollowUpExtractor()
    repository = SQLiteRepository(str(tmp_path / "followup.sqlite3"))
    app = create_app(service=IngestionService(FakeExtractor()), analyzer=RequirementsAnalyzer(extractor), repository=repository)
    client = TestClient(app)
    brd_id = client.post("/api/brd/upload", files={"file": ("followup.md", b"# Followup", "text/markdown")}).json()["brd_id"]
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()
    session_id = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]}).json()["session_id"]
    with client.websocket_connect(f"/ws/hitl/{session_id}") as ws:
        assert ws.receive_json()["type"] == "resumed"
        first = ws.receive_json()
        assert first["question"]["question_id"] == "Q-001"
        ws.send_json({"type": "answer", "question_id": "Q-001", "answer": "Managers handle it."})
        assert ws.receive_json()["type"] == "answer_acknowledged"
        follow = ws.receive_json()
        assert follow["type"] == "question"
        assert follow["question"]["question_id"] == "Q-101"
        ws.send_json({"type": "answer", "question_id": "Q-101", "answer": "Rejected requests are returned to the requester."})
        assert ws.receive_json()["type"] == "answer_acknowledged"
        assert ws.receive_json()["type"] == "completed"
    state = client.get(f"/api/hitl/session/{session_id}").json()
    assert state["follow_up_round"] == 1
    assert {item["question_id"] for item in state["answers"]} == {"Q-001", "Q-101"}
    assert client.get(f"/api/hitl/session/{session_id}").json()["status"] == "COMPLETED"
