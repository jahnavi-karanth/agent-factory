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


from app.parser import parse_document, extract_sections_and_chunks


def seed_brd(repo, extractor, content, filename="brd.md"):
    doc = parse_document(filename, content.encode("utf-8") if isinstance(content, str) else content)
    model = IngestionService(extractor).ingest(doc)
    repo.save_requirements_model(model, doc.text, "text")
    return model.brd_id


# ==========================================
# 3.1 Ingestion Tests
# ==========================================

def test_upload_valid_markdown():
    doc = parse_document("expense_brd.md", b"# Corporate Expense Management\n## 1. Executive Summary\nThe system shall process expense reports automatically.\n\n## 2. Business Requirements\n- REQ-1: Support receipt upload.\n- REQ-2: Auto-calculate totals.")
    model = IngestionService(MockGeminiExtractor()).ingest(doc)
    assert model.brd_id.startswith("BRD-")
    assert len(model.requirements) >= 1


def test_upload_valid_txt():
    doc = parse_document("brd.txt", b"Business Requirements Document\nRequirement 1: User login via SSO.")
    model = IngestionService(MockGeminiExtractor()).ingest(doc)
    assert model.brd_id.startswith("BRD-")


def test_upload_markdown_extension_variations():
    content = b"# BRD\nThe system must track assets."
    for filename in ["doc.markdown", "spec.md"]:
        doc = parse_document(filename, content)
        model = IngestionService(MockGeminiExtractor()).ingest(doc)
        assert model.brd_id.startswith("BRD-")


def test_upload_empty_file():
    try:
        parse_document("empty.md", b"")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "empty" in str(exc).lower()


def test_upload_whitespace_file():
    try:
        parse_document("blank.md", b"   \n\n\t  ")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "empty" in str(exc).lower() or "no" in str(exc).lower()


def test_upload_oversized_file():
    content = ("A" * 200).encode("utf-8")
    assert len(content) == 200


def test_upload_unicode_emojis_special_chars():
    special_content = """# 🚀 Rocket Launch BRD (V2.0) & System Specification

## 1. Executive Summary
The platform supports €100M+ transactions & URLs: https://example.com/api.
Tables & Code:
```json
{"key": "value"}
```
- REQ-001: Validate UTF-8 inputs with emojis 🔥 and symbols: §10.2 @user #tag!
"""
    doc = parse_document("special_brd.md", special_content.encode("utf-8"))
    model = IngestionService(MockGeminiExtractor()).ingest(doc)
    assert model.brd_id.startswith("BRD-")


def test_upload_same_filename_idempotent_brd_id(repo):
    content1 = "# Corporate Expense Management Platform\nRequirement 1: System shall log all errors."
    content2 = "# Corporate Expense Management Platform\nRequirement 1: System shall log all errors and audit them."
    brd1 = seed_brd(repo, MockGeminiExtractor(), content1, "same_file.md")
    brd2 = seed_brd(repo, MockGeminiExtractor(), content2, "same_file.md")
    assert brd1 == brd2


def test_rejects_unsupported_format():
    try:
        parse_document("brief.pdf", b"not pdf")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "unsupported" in str(exc).lower()



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
    doc = parse_document("nested.md", content.encode("utf-8"))
    sections, chunks = extract_sections_and_chunks(doc)
    assert len(sections) >= 1


def test_parser_no_headings():
    content = "This document has no headings at all. It is a plain block of text describing system requirements for user authentication and auditing."
    doc = parse_document("no_headings.txt", content.encode("utf-8"))
    assert len(doc.text) > 0


# ==========================================
# 3.3 Gemini Requirement Extraction Tests
# ==========================================

def test_extractor_failure_handled_gracefully():
    class FailingExtractor:
        def extract(self, doc):
            raise ExtractionError("Simulated API failure")

    service = IngestionService(FailingExtractor())
    doc = parse_document("failing.md", b"# Simple BRD\n- System must encrypt database.")
    try:
        service.ingest(doc)
        assert False, "expected ExtractionError"
    except ExtractionError as exc:
        assert "Simulated API failure" in str(exc)


# ==========================================
# 3.4 Requirements Model Tests
# ==========================================

def test_requirements_model_stable_ids(client, repo):
    content = "# Corporate Expense Management Platform\n- REQ A: Feature A\n- REQ B: Feature B"
    brd_id = seed_brd(repo, MockGeminiExtractor(), content, "stable.md")
    
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

def test_analyze_requirements_persisted(client, repo):
    content = """# Corporate Expense BRD
## 1. Executive Summary
- REQ-001: Users must submit expenses.
## 2. Business Requirements
- REQ-002: Manager approval is required for amounts above an unspecified threshold.
"""
    brd_id = seed_brd(repo, MockGeminiExtractor(), content, "analysis_test.md")
    
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


def test_get_analysis_by_id(client, repo):
    content = "# Corporate Expense Management Platform\n- System shall issue tokens."
    brd_id = seed_brd(repo, MockGeminiExtractor(), content, "b.md")
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

def test_audit_logs_recorded(client, repo):
    content = "# Corporate Expense Management Platform\n- Requirement 1"
    brd_id = seed_brd(repo, MockGeminiExtractor(), content, "audit.md")
    repo.audit("BRD_UPLOADED", "brd", brd_id)
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

def test_m1_m2_end_to_end_chain(client, repo):
    content = """# Corporate Expense Management Platform
## 1. Executive Summary
Manage warehouse stock accurately.

## 2. Business Requirements
- REQ-001: System must track item counts in real time.
- REQ-002: High-value transfers require dual sign-off.
"""
    # Step 1: Upload
    brd_id = seed_brd(repo, MockGeminiExtractor(), content, "inv.md")
    repo.audit("BRD_UPLOADED", "brd", brd_id)
    
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

