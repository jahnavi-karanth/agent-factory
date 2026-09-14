from __future__ import annotations

import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import RequirementsModel
from app.repository import SQLiteRepository
from app.service import IngestionService
from app.analyzer import RequirementsAnalyzer
from app.workflow import RequirementsWorkflow


class MockWorkflowExtractor:
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


@pytest.fixture
def repo(tmp_path):
    return SQLiteRepository(str(tmp_path / "langgraph_test.sqlite3"))


@pytest.fixture
def client(repo):
    mock = MockWorkflowExtractor()
    app = create_app(
        service=IngestionService(mock),
        analyzer=RequirementsAnalyzer(mock),
        repository=repo
    )
    return TestClient(app)


def get_auth_token(client):
    # Register & Login user to get JWT token
    reg = client.post("/auth/register", json={"email": "testuser@example.com", "password": "password123"})
    if reg.status_code == 201:
        return reg.json()["access_token"]
    login = client.post("/auth/token", json={"email": "testuser@example.com", "password": "password123"})
    return login.json()["access_token"]


# ==========================================
# 7.1 & 7.2 StateGraph & Node Execution
# ==========================================

def test_langgraph_requirements_workflow_direct_execution(repo):
    mock = MockWorkflowExtractor()
    analyzer = RequirementsAnalyzer(mock)
    ingestion = IngestionService(mock)
    
    # Upload BRD
    doc = type("Doc", (), {"filename": "test.md", "text": "# Corporate Expense Management Platform\n- REQ-001: Expense\n- REQ-002: Approval", "headings": []})()
    model = ingestion.ingest(doc)
    repo.save_requirements_model(model, doc.text, "markdown")
    
    # Create project & workflow run
    repo.create_project("PROJ-TEST1", "Test Project")
    run_info = repo.create_workflow_run("PROJ-TEST1", model.brd_id)
    run_id = run_info["run_id"]
    
    workflow = RequirementsWorkflow(repo, analyzer)
    
    # Start graph execution (will interrupt on clarification_hitl)
    result = workflow.start("PROJ-TEST1", run_id, model.brd_id)
    assert "__interrupt__" in result
    interrupt_payload = result["__interrupt__"][0].value
    assert interrupt_payload["type"] == "clarification_request"
    assert interrupt_payload["run_id"] == run_id
    assert len(interrupt_payload["questions"]) == 1
    
    # Resume graph with clarification answer (will move to approval_gate and interrupt)
    answer_payload = [{"question_id": "Q-001", "answer": "The manager threshold is five hundred dollars."}]
    res2 = workflow.resume(run_id, answer_payload)
    assert "__interrupt__" in res2
    interrupt2 = res2["__interrupt__"][0].value
    assert interrupt2["type"] == "approval_request"
    
    # Resume graph with approval decision
    res3 = workflow.resume(run_id, {"decision": "APPROVE"})
    assert res3.get("status") == "COMPLETED"


# ==========================================
# 7.3 & 7.4 Interrupts & Command(resume=...)
# ==========================================

def test_langgraph_rejection_and_revision_loop(repo):
    mock = MockWorkflowExtractor()
    analyzer = RequirementsAnalyzer(mock)
    ingestion = IngestionService(mock)
    
    doc = type("Doc", (), {"filename": "test2.md", "text": "# Corporate Expense Management Platform\n- REQ-001: Expense", "headings": []})()
    model = ingestion.ingest(doc)
    repo.save_requirements_model(model, doc.text, "markdown")
    repo.create_project("PROJ-REJECT", "Reject Test Project")
    run_info = repo.create_workflow_run("PROJ-REJECT", model.brd_id)
    run_id = run_info["run_id"]
    
    workflow = RequirementsWorkflow(repo, analyzer)
    
    # Start -> Interrupt at clarification
    _res1 = workflow.start("PROJ-REJECT", run_id, model.brd_id)
    
    # Resume clarification -> Interrupt at approval
    answer_payload = [{"question_id": "Q-001", "answer": "The manager threshold is five hundred dollars."}]
    _res2 = workflow.resume(run_id, answer_payload)
    
    # Reject with feedback -> Routing takes it back to resolve_requirements -> Approval gate interrupt
    res3 = workflow.resume(run_id, {"decision": "REJECT", "feedback": "Add SLA requirement for approval."})
    assert "__interrupt__" in res3
    interrupt3 = res3["__interrupt__"][0].value
    assert interrupt3["type"] == "approval_request"
    assert interrupt3["revision_count"] == 1
    
    # Now Approve
    res4 = workflow.resume(run_id, {"decision": "APPROVE"})
    assert res4.get("status") == "COMPLETED"


# ==========================================
# 7.5 Checkpointing & 7.6 Project/Run Scoping REST APIs
# ==========================================

def test_rest_workflow_project_run_scoping_and_execution(client):
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    
    # 1. Create Project
    proj_resp = client.post("/projects", json={"name": "Project Alpha"}, headers=headers)
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]
    
    # 2. Upload BRD linked to Project
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense\n- REQ-002: Approval"
    brd = client.post(f"/api/brd/upload?project_id={project_id}", files={"file": ("brd.md", content, "text/markdown")}).json()
    brd_id = brd["brd_id"]
    
    # 3. Trigger Workflow via REST
    wf_resp = client.post(
        f"/projects/{project_id}/workflows/requirements",
        json={"brd_id": brd_id},
        headers=headers
    )
    assert wf_resp.status_code == 202
    run_data = wf_resp.json()
    run_id = run_data["run_id"]
    assert run_data["status"] == "PAUSED"
    
    # 4. Check Run Status
    run_check = client.get(f"/projects/{project_id}/runs/{run_id}", headers=headers).json()
    assert run_check["status"] == "PAUSED"
    
    # 5. Resume via HITL REST Response
    answer_payload = [{"question_id": "Q-001", "answer": "Approval threshold is five hundred dollars."}]
    res_resp = client.post(
        f"/projects/{project_id}/runs/{run_id}/hitl/response",
        json={"payload": answer_payload},
        headers=headers
    )
    assert res_resp.status_code == 200
    res_data = res_resp.json()
    assert res_data["status"] == "PAUSED" # At approval gate
    
    # 6. Approve via Approval Endpoint
    appr_resp = client.post(
        f"/projects/{project_id}/runs/{run_id}/approval",
        json={"payload": {"decision": "APPROVE"}},
        headers=headers
    )
    assert appr_resp.status_code == 200
    assert appr_resp.json()["status"] == "COMPLETED"


# ==========================================
# 7.9 SSE Stream Tests
# ==========================================

def test_workflow_sse_events_stream(client):
    token = get_auth_token(client)
    headers = {"Authorization": f"Bearer {token}"}
    
    proj_resp = client.post("/projects", json={"name": "SSE Project"}, headers=headers).json()
    project_id = proj_resp["project_id"]
    
    content = "# Corporate Expense Management Platform\n- REQ-001: Expense"
    brd = client.post(f"/api/brd/upload?project_id={project_id}", files={"file": ("sse.md", content, "text/markdown")}).json()
    
    wf = client.post(f"/projects/{project_id}/workflows/requirements", json={"brd_id": brd["brd_id"]}, headers=headers).json()
    run_id = wf["run_id"]
    
    events_resp = client.get(f"/projects/{project_id}/runs/{run_id}/events", headers=headers)
    assert events_resp.status_code == 200
    assert "event-stream" in events_resp.headers["content-type"]
    body = events_resp.text
    assert "workflow_started" in body
    assert "clarification_required" in body
