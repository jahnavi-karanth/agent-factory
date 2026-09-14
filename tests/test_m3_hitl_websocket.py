from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import RequirementsModel
from app.analysis_models import RequirementsAnalysis
from app.repository import SQLiteRepository
from app.service import IngestionService
from app.analyzer import RequirementsAnalyzer


class MockHITLExtractor:
    def __init__(self, generate_followups: bool = False):
        self.generate_followups = generate_followups

    def extract(self, document):
        return {
            "title": "Corporate Expense Management Platform",
            "business_problem": "Expense tracking.",
            "business_objectives": ["Automate expenses."],
            "stakeholders": ["Employees"],
            "user_roles": ["Employee", "Manager"],
            "requirements": [
                {"id": "REQ-001", "type": "functional", "description": "Users submit expenses.", "source": {"title": "1. Executive Summary"}, "priority": None},
                {"id": "REQ-002", "type": "functional", "description": "Manager approval threshold required.", "source": {"title": "2. Business Requirements"}, "priority": None},
            ],
            "non_functional_requirements": [], "business_rules": [], "constraints": [], "assumptions": [],
            "data_requirements": [], "external_dependencies": [], "success_criteria": [],
        }

    def generate_json(self, prompt, schema):
        if "decisions" in schema.get("required", []) or "decisions" in schema.get("properties", {}):
            return {
                "decisions": [
                    {"question_id": "Q-001", "decision": "Default approval threshold is set to $500.", "reason": "Conservative business default."}
                ]
            }
        if "questions" in schema.get("required", []) or "questions" in schema.get("properties", {}):
            if self.generate_followups:
                return {
                    "questions": [
                        {"question_id": "Q-101", "issue_id": "GAP-001", "question": "Should receipts be mandatory above $50?", "reason": "Follow-up clarification required.", "priority": "MEDIUM"}
                    ]
                }
            return {"questions": []}
        return {
            "issues": [{
                "issue_id": "GAP-001", "type": "gap", "severity": "HIGH",
                "title": "Threshold missing", "description": "Approval threshold is unspecified.",
                "affected_requirements": ["REQ-002"], "reason": "Required for workflow.",
                "clarification_required": True, "severity_reason": "High impact"
            }],
            "clarification_questions": [{
                "question_id": "Q-001", "issue_id": "GAP-001",
                "affected_requirements": ["REQ-002"],
                "question": "What is the manager approval dollar threshold?",
                "reason": "Threshold is not specified.", "priority": "HIGH"
            }]
        }


class MockReadyExtractor:
    def extract(self, document):
        return {
            "title": "Corporate Expense Management Platform",
            "business_problem": "Expense tracking.",
            "requirements": [{"id": "REQ-001", "type": "functional", "description": "Users submit expenses.", "source": {}, "priority": None}],
        }

    def generate_json(self, prompt, schema):
        return {"issues": [], "clarification_questions": []}


@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(str(tmp_path / "hitl_test.sqlite3"))


@pytest.fixture
def client(repo):
    mock = MockHITLExtractor(generate_followups=False)
    app = create_app(
        service=IngestionService(mock),
        analyzer=RequirementsAnalyzer(mock),
        repository=repo
    )
    return TestClient(app)


# ==========================================
# 6.1 HITL Session Creation Tests
# ==========================================

def test_hitl_session_creation_success(client):
    content = "# Corporate Expense Management Platform\n## 1. Executive Summary\n- REQ-001: Expense submission\n## 2. Business Requirements\n- REQ-002: Approval"
    brd = client.post("/api/brd/upload", files={"file": ("brd.md", content, "text/markdown")}).json()
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd["brd_id"]}).json()
    
    session_resp = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]})
    assert session_resp.status_code == 200
    session_data = session_resp.json()
    assert "session_id" in session_data
    assert session_data["session_id"].startswith("HITL-")
    assert session_data["status"] == "ACTIVE"


def test_hitl_session_creation_invalid_status_conflict(repo):
    mock_ready = MockReadyExtractor()
    ready_app = create_app(
        service=IngestionService(mock_ready),
        analyzer=RequirementsAnalyzer(mock_ready),
        repository=repo
    )
    ready_client = TestClient(ready_app)
    
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense submission"
    brd = ready_client.post("/api/brd/upload", files={"file": ("brd2.md", content, "text/markdown")}).json()
    analysis = ready_client.post("/api/requirements/analyze", json={"brd_id": brd["brd_id"]}).json()
    assert analysis["quality_status"] == "READY"
    
    session_resp = ready_client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]})
    assert session_resp.status_code == 409
    assert "READY_FOR_CLARIFICATION" in session_resp.json()["detail"]


def test_hitl_session_creation_nonexistent_analysis_404(client):
    session_resp = client.post("/api/hitl/session", json={"analysis_id": "ANALYSIS-FAKE"})
    assert session_resp.status_code == 404


# ==========================================
# 6.2 & 6.3 WebSocket Flow & Answer Validation
# ==========================================

def test_websocket_hitl_full_flow(client):
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense\n- REQ-002: Approval"
    brd = client.post("/api/brd/upload", files={"file": ("ws.md", content, "text/markdown")}).json()
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd["brd_id"]}).json()
    session = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]}).json()
    session_id = session["session_id"]
    
    with client.websocket_connect(f"/ws/hitl/{session_id}") as ws:
        # Message 1: Resumed
        msg1 = ws.receive_json()
        assert msg1["type"] == "resumed"
        assert msg1["session_id"] == session_id
        
        # Message 2: Question
        msg2 = ws.receive_json()
        assert msg2["type"] == "question"
        q_id = msg2["question"]["question_id"]
        assert q_id == "Q-001"
        
        # Invalid response test: wrong question_id
        ws.send_json({"type": "answer", "question_id": "Q-WRONG", "answer": "1000"})
        err_msg = ws.receive_json()
        assert err_msg["type"] == "error"
        # Receive re-presented question
        msg2_retry = ws.receive_json()
        assert msg2_retry["type"] == "question"
        
        # Send valid answer with sufficient length
        ws.send_json({"type": "answer", "question_id": q_id, "answer": "The manager approval threshold is specified as one thousand dollars per expense report."})
        ack_msg = ws.receive_json()
        assert ack_msg["type"] == "answer_acknowledged"
        assert ack_msg["question_id"] == q_id
        
        # Final message: completed
        comp_msg = ws.receive_json()
        assert comp_msg["type"] == "completed"

    # Verify session status updated in database
    get_session = client.get(f"/api/hitl/session/{session_id}").json()
    assert get_session["status"] == "COMPLETED"
    assert len(get_session["answers"]) == 1
    assert get_session["answers"][0]["answer"] == "The manager approval threshold is specified as one thousand dollars per expense report."


def test_websocket_hitl_reconnection_survival(client):
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense\n- REQ-002: Approval"
    brd = client.post("/api/brd/upload", files={"file": ("recon.md", content, "text/markdown")}).json()
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd["brd_id"]}).json()
    session = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]}).json()
    session_id = session["session_id"]

    # Connect, read question, disconnect without answering
    with client.websocket_connect(f"/ws/hitl/{session_id}") as ws:
        _resumed = ws.receive_json()
        _question = ws.receive_json()

    # Verify session is still active
    s_data = client.get(f"/api/hitl/session/{session_id}").json()
    assert s_data["status"] == "ACTIVE"

    # Reconnect and complete
    with client.websocket_connect(f"/ws/hitl/{session_id}") as ws2:
        resumed2 = ws2.receive_json()
        assert resumed2["type"] == "resumed"
        q2 = ws2.receive_json()
        assert q2["type"] == "question"
        ws2.send_json({"type": "answer", "question_id": q2["question"]["question_id"], "answer": "The manager approval threshold is specified as five hundred dollars."})
        ws2.receive_json() # ack
        ws2.receive_json() # completed


# ==========================================
# 6.4 & 6.5 Undecided Answers & Best Decisions
# ==========================================

def test_websocket_hitl_undecided_best_decisions(client, monkeypatch):
    monkeypatch.setenv("MAX_FOLLOW_UP_ROUNDS", "0")
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense\n- REQ-002: Approval"
    brd = client.post("/api/brd/upload", files={"file": ("undecided.md", content, "text/markdown")}).json()
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd["brd_id"]}).json()
    session = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]}).json()
    session_id = session["session_id"]

    with client.websocket_connect(f"/ws/hitl/{session_id}") as ws:
        ws.receive_json() # resumed
        q = ws.receive_json() # question
        ws.send_json({"type": "answer", "question_id": q["question"]["question_id"], "answer": "undecided"})
        ws.receive_json() # ack
        
        # When MAX_FOLLOW_UP_ROUNDS is exceeded with quality flags (undecided), best decisions are issued
        msg_decisions = ws.receive_json()
        assert msg_decisions["type"] == "best_decisions"
        assert len(msg_decisions["decisions"]) >= 1
        
        comp = ws.receive_json()
        assert comp["type"] == "completed"


# ==========================================
# 6.6 Resolved Requirements Model Verification
# ==========================================

def test_resolved_requirements_model_persisted(client):
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense\n- REQ-002: Approval"
    brd = client.post("/api/brd/upload", files={"file": ("res_model.md", content, "text/markdown")}).json()
    brd_id = brd["brd_id"]
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()
    session = client.post("/api/hitl/session", json={"analysis_id": analysis["analysis_id"]}).json()
    session_id = session["session_id"]

    with client.websocket_connect(f"/ws/hitl/{session_id}") as ws:
        ws.receive_json()
        q = ws.receive_json()
        ws.send_json({"type": "answer", "question_id": q["question"]["question_id"], "answer": "The manager approval threshold is specified as five hundred dollars."})
        ws.receive_json() # ack
        ws.receive_json() # completed

    # Check that latest requirements model is marked resolved
    latest_reqs = client.get(f"/api/brd/{brd_id}/requirements").json()
    assert latest_reqs["extraction_metadata"].get("resolved") == "true"
    
    # Check version history preserved
    versions = client.get(f"/api/brd/{brd_id}/versions").json()
    assert len(versions) >= 2
