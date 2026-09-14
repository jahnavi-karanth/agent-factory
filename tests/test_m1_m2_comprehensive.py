from __future__ import annotations

import io
import os
import json
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.models import RequirementsModel, Requirement
from app.analysis_models import RequirementsAnalysis
from app.repository import SQLiteRepository
from app.service import IngestionService
from app.analyzer import RequirementsAnalyzer
from app.llm import ExtractionError


class MockGeminiExtractor:
    def extract(self, document):
        return {
            "title": "Corporate Expense Management Platform",
            "business_problem": "Manual processing.",
            "business_objectives": ["Automate expenses."],
            "stakeholders": ["Employees"],
            "user_roles": ["Employee", "Manager"],
            "requirements": [
                {"id": "REQ-001", "type": "functional", "description": "System shall process receipts.", "source": {"title": "1. Executive Summary"}, "priority": None},
                {"id": "REQ-002", "type": "functional", "description": "System shall calculate totals.", "source": {"title": "2. Business Requirements"}, "priority": None},
            ],
            "non_functional_requirements": [],
            "business_rules": [],
            "constraints": [],
            "assumptions": [],
            "data_requirements": [],
            "external_dependencies": [],
            "success_criteria": [],
        }

    def generate_json(self, prompt, schema):
        if "issues" in schema.get("required", []) or "issues" in schema.get("properties", {}):
            return {
                "issues": [{
                    "issue_id": "GAP-001", "type": "gap", "severity": "HIGH",
                    "title": "Threshold missing", "description": "Approval threshold is unspecified.",
                    "affected_requirements": ["REQ-002"], "reason": "Required for workflow.",
                    "clarification_required": True, "severity_reason": "High business impact"
                }],
                "clarification_questions": [{
                    "question_id": "Q-001", "issue_id": "GAP-001",
                    "affected_requirements": ["REQ-002"],
                    "question": "What is the approval amount threshold?",
                    "reason": "Threshold is not specified.", "priority": "HIGH"
                }]
            }
        return {}


@pytest.fixture
def repo(tmp_path):
    db_path = str(tmp_path / "test.sqlite3")
    return SQLiteRepository(db_path)


@pytest.fixture
def client(repo):
    mock_extractor = MockGeminiExtractor()
    app = create_app(
        service=IngestionService(mock_extractor),
        analyzer=RequirementsAnalyzer(mock_extractor),
        repository=repo
    )
    return TestClient(app)


# ==========================================
# 3.1 BRD Upload Tests
# ==========================================

def test_upload_valid_markdown(client):
    md_content = """# Corporate Expense Management
## 1. Executive Summary
The system shall process expense reports automatically.

## 2. Business Requirements
- REQ-1: Support receipt upload.
- REQ-2: Auto-calculate totals.
"""
    response = client.post(
        "/api/brd/upload",
        files={"file": ("expense_brd.md", md_content, "text/markdown")}
    )
    assert response.status_code == 200
    data = response.json()
    assert "brd_id" in data
    assert data["brd_id"].startswith("BRD-")
    assert len(data["requirements"]) >= 1


def test_upload_valid_txt(client):
    txt_content = "Business Requirements Document\nRequirement 1: User login via SSO."
    response = client.post(
        "/api/brd/upload",
        files={"file": ("brd.txt", txt_content, "text/plain")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["brd_id"].startswith("BRD-")


def test_upload_markdown_extension_variations(client):
    content = "# BRD\nThe system must track assets."
    for filename in ["doc.markdown", "spec.md"]:
        resp = client.post(
            "/api/brd/upload",
            files={"file": (filename, content, "text/markdown")}
        )
        assert resp.status_code == 200


def test_upload_empty_file(client):
    response = client.post(
        "/api/brd/upload",
        files={"file": ("empty.md", "", "text/markdown")}
    )
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower() or "brd" in response.json()["detail"].lower()


def test_upload_whitespace_file(client):
    response = client.post(
        "/api/brd/upload",
        files={"file": ("blank.md", "   \n\n\t  ", "text/markdown")}
    )
    assert response.status_code == 400


def test_upload_oversized_file(client, monkeypatch):
    monkeypatch.setattr("app.main.MAX_UPLOAD_BYTES", 100)
    big_content = "A" * 200
    response = client.post(
        "/api/brd/upload",
        files={"file": ("large.md", big_content, "text/markdown")}
    )
    assert response.status_code == 413
    assert "exceeds" in response.json()["detail"].lower()


def test_upload_unicode_emojis_special_chars(client):
    special_content = """# 🚀 Rocket Launch BRD (V2.0) & System Specification

## 1. Executive Summary
The platform supports €100M+ transactions & URLs: https://example.com/api.
Tables & Code:
```json
{"key": "value"}
```
- REQ-001: Validate UTF-8 inputs with emojis 🔥 and symbols: §10.2 @user #tag!
"""
    response = client.post(
        "/api/brd/upload",
        files={"file": ("special_brd.md", special_content, "text/markdown")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["brd_id"].startswith("BRD-")


def test_upload_same_filename_idempotent_brd_id(client):
    content1 = "# Corporate Expense Management Platform\nRequirement 1: System shall log all errors."
    content2 = "# Corporate Expense Management Platform\nRequirement 1: System shall log all errors and audit them."
    resp1 = client.post("/api/brd/upload", files={"file": ("same_file.md", content1, "text/markdown")})
    resp2 = client.post("/api/brd/upload", files={"file": ("same_file.md", content2, "text/markdown")})
    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert resp1.json()["brd_id"] == resp2.json()["brd_id"]


def test_upload_missing_file_payload(client):
    response = client.post("/api/brd/upload")
    assert response.status_code == 422  # Unprocessable entity


def test_rejects_unsupported_format(client):
    response = client.post("/api/brd/upload", files={"file": ("brief.pdf", b"not pdf", "application/pdf")})
    assert response.status_code == 400
    assert "unsupported BRD format" in response.json()["detail"]


# ==========================================
# 3.2 Parsing Tests
# ==========================================

def test_parser_nested_and_unusual_headings(client):
    content = """
# 1. Executive Summary
Preamble content before any section.

### Sub-sub section heading
- Item 1

## 2. Business Requirements
Some text here.
"""
    response = client.post(
        "/api/brd/upload",
        files={"file": ("nested.md", content, "text/markdown")}
    )
    assert response.status_code == 200


def test_parser_no_headings(client):
    content = "This document has no headings at all. It is a plain block of text describing system requirements for user authentication and auditing."
    response = client.post(
        "/api/brd/upload",
        files={"file": ("no_headings.txt", content, "text/plain")}
    )
    assert response.status_code == 200


# ==========================================
# 3.3 Gemini Requirement Extraction Tests
# ==========================================

def test_extractor_failure_handled_gracefully(repo):
    class FailingExtractor:
        def extract(self, doc):
            raise ExtractionError("Simulated API failure")

    failing_app = create_app(service=IngestionService(FailingExtractor()), repository=repo)
    failing_client = TestClient(failing_app)
    
    content = "# Simple BRD\n- System must encrypt database."
    response = failing_client.post(
        "/api/brd/upload",
        files={"file": ("failing.md", content, "text/markdown")}
    )
    assert response.status_code == 502
    assert response.json()["error"] == "brd_ingestion_failed"


# ==========================================
# 3.4 Requirements Model Tests
# ==========================================

def test_requirements_model_stable_ids(client):
    content = "# Corporate Expense Management Platform\n- REQ A: Feature A\n- REQ B: Feature B"
    response = client.post(
        "/api/brd/upload",
        files={"file": ("stable.md", content, "text/markdown")}
    )
    assert response.status_code == 200
    brd_id = response.json()["brd_id"]
    
    # Retrieve model twice and compare requirement IDs
    get1 = client.get(f"/api/brd/{brd_id}/requirements").json()
    get2 = client.get(f"/api/brd/{brd_id}/requirements").json()
    
    req_ids_1 = [r["id"] for r in get1["requirements"]]
    req_ids_2 = [r["id"] for r in get2["requirements"]]
    
    assert req_ids_1 == req_ids_2
    assert all(rid.startswith("REQ-") for rid in req_ids_1)


# ==========================================
# 4.1 & 4.2 Requirements Analysis & Quality Status
# ==========================================

def test_analyze_requirements_persisted(client):
    content = """# Corporate Expense BRD
## 1. Executive Summary
- REQ-001: Users must submit expenses.
## 2. Business Requirements
- REQ-002: Manager approval is required for amounts above an unspecified threshold.
"""
    upload_resp = client.post(
        "/api/brd/upload",
        files={"file": ("analysis_test.md", content, "text/markdown")}
    )
    brd_id = upload_resp.json()["brd_id"]
    
    analyze_resp = client.post("/api/requirements/analyze", json={"brd_id": brd_id})
    assert analyze_resp.status_code == 200
    analysis = analyze_resp.json()
    
    assert "analysis_id" in analysis
    assert analysis["brd_id"] == brd_id
    assert analysis["quality_status"] in ["READY", "READY_FOR_CLARIFICATION", "NEEDS_REWORK", "INVALID"]
    assert isinstance(analysis["issues"], list)
    assert isinstance(analysis["clarification_questions"], list)


def test_analyze_requirements_invalid_brd_id(client):
    response = client.post("/api/requirements/analyze", json={"brd_id": "BRD-NONEXISTENT"})
    assert response.status_code in [404, 503]


def test_get_analysis_by_id(client):
    content = "# Corporate Expense Management Platform\n- System shall issue tokens."
    brd_id = client.post("/api/brd/upload", files={"file": ("b.md", content, "text/markdown")}).json()["brd_id"]
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()
    
    get_resp = client.get(f"/api/analysis/{analysis['analysis_id']}")
    assert get_resp.status_code == 200
    assert get_resp.json()["analysis_id"] == analysis["analysis_id"]


def test_get_nonexistent_analysis_404(client):
    response = client.get("/api/analysis/ANALYSIS-NONEXISTENT")
    assert response.status_code == 404


# ==========================================
# 4.4 Audit Log Verification
# ==========================================

def test_audit_logs_recorded(client):
    content = "# Corporate Expense Management Platform\n- Requirement 1"
    brd_id = client.post("/api/brd/upload", files={"file": ("audit.md", content, "text/markdown")}).json()["brd_id"]
    analysis_id = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()["analysis_id"]
    
    audit_resp = client.get(f"/api/audit?entity_id={brd_id}")
    assert audit_resp.status_code == 200
    events = audit_resp.json()
    actions = [e["action"] for e in events]
    assert "BRD_UPLOADED" in actions
    assert "ANALYSIS_STARTED" in actions


# ==========================================
# 5. M1 -> M2 Integration Verification
# ==========================================

def test_m1_m2_end_to_end_chain(client):
    content = """# Corporate Expense Management Platform
## 1. Executive Summary
Manage warehouse stock accurately.

## 2. Business Requirements
- REQ-001: System must track item counts in real time.
- REQ-002: High-value transfers require dual sign-off.
"""
    # Step 1: Upload
    upload = client.post("/api/brd/upload", files={"file": ("inv.md", content, "text/markdown")}).json()
    brd_id = upload["brd_id"]
    
    # Step 2: Fetch Requirements
    reqs = client.get(f"/api/brd/{brd_id}/requirements").json()
    assert reqs["brd_id"] == brd_id
    req_ids = {r["id"] for r in reqs["requirements"]}
    
    # Step 3: Analyze Requirements
    analysis = client.post("/api/requirements/analyze", json={"brd_id": brd_id}).json()
    assert analysis["brd_id"] == brd_id
    
    # Step 4: Verify questions map to requirements
    for q in analysis["clarification_questions"]:
        assert q["question_id"].startswith("Q-")
        for aff in q["affected_requirements"]:
            assert aff in req_ids
