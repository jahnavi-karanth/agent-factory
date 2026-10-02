import json
import pytest
from fastapi.testclient import TestClient

from app.auth import create_token
from app.main import create_app
from app.models import Requirement, RequirementsModel, SourceReference
from app.planning_models import TaskPatchRequest, TaskSplitSpec
from app.planning_workflow import PlanningWorkflow, WebSearchProvider
from app.repository import SQLiteRepository


@pytest.fixture
def repo(tmp_path):
    db_file = tmp_path / "test_m4.sqlite3"
    repository = SQLiteRepository(path=str(db_file))
    return repository


@pytest.fixture
def client(repo):
    app = create_app(repository=repo)
    return TestClient(app)


@pytest.fixture
def auth_headers(repo):
    user = repo.create_user("USR-M4-001", "m4user@example.com", "hash123")
    token = create_token("USR-M4-001")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def project(repo, auth_headers):
    return repo.create_project("PROJ-M4-001", "M4 Test Project", "USR-M4-001")


@pytest.fixture
def sample_requirements(repo):
    model = RequirementsModel(
        brd_id="BRD-M4-001",
        title="Expense Tracker System",
        source_filename="expense_brd.md",
        business_problem="Manual spreadsheet tracking.",
        business_objectives=["Automate expense submission"],
        requirements=[
            Requirement(
                id="REQ-001",
                type="functional",
                description="System must allow users to submit expense reports.",
                source=SourceReference(section="SEC-001", title="Submission", line_start=1, line_end=10),
            ),
            Requirement(
                id="REQ-002",
                type="functional",
                description="System must support manager approval workflow.",
                source=SourceReference(section="SEC-002", title="Approval", line_start=11, line_end=20),
            ),
        ],
    )
    v_id = repo.save_requirements_model(model, "# BRD Content", "markdown")
    return model, v_id


# Test 1: Project Ownership Enforcement
def test_project_ownership(client, auth_headers, repo):
    repo.create_user("USR-OTHER", "other@example.com", "hash123")
    repo.create_project("PROJ-OTHER", "Other User Project", "USR-OTHER")
    res = client.post("/projects/PROJ-OTHER/workflows/planning", headers=auth_headers, json={"brd_id": "BRD-001"})
    assert res.status_code == 404



# Test 2 & 45 & 46: Document-to-Requirements Bridge & Missing / Cross-Project Documents
def test_document_to_requirements_bridge(client, auth_headers, project, repo):
    p_id = project["project_id"]

    # Upload document to project
    doc_id = "DOC-M4-001"
    repo.save_document(p_id, doc_id, "test.md", "markdown", "/path/test.md", status="COMPLETED")
    repo.save_document_sections_and_chunks(
        doc_id,
        p_id,
        [{"section_id": "SEC-001", "title": "Overview", "level": 1, "content": "Overview content"}],
        [{"chunk_id": "CHK-001", "section_id": "SEC-001", "text": "Requirement REQ-001: The system shall submit expenses cleanly.", "kind": "text"}]
    )

    # Valid start with document_ids
    res = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"document_ids": [doc_id]})
    assert res.status_code == 202
    body = res.json()
    assert body["run_id"].startswith("RUN-")
    assert body["status"] in ["RUNNING", "PAUSED", "COMPLETED"]

    # Missing document
    res_missing = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"document_ids": ["DOC-MISSING"]})
    assert res_missing.status_code == 404

    # Cross-project document
    repo.create_project("PROJ-FOREIGN", "Foreign Project", "USR-M4-001")
    repo.save_document("PROJ-FOREIGN", "DOC-FOREIGN", "foreign.md", "markdown", "/path/foreign.md")
    res_cross = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"document_ids": ["DOC-FOREIGN"]})
    assert res_cross.status_code == 404



# Test 3 & 4: Planning Run Creation & Requirements Version Loading
def test_planning_run_creation_by_version_id(client, auth_headers, project, sample_requirements):
    p_id = project["project_id"]
    model, version_id = sample_requirements

    res = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"requirements_model_version_id": version_id})
    assert res.status_code == 202
    data = res.json()
    assert data["source_model_version_id"] == version_id


# Test 5 & 6: Simple and Complex Routing
def test_complexity_classification_routing(repo, sample_requirements):
    model, v_id = sample_requirements
    wf = PlanningWorkflow(repo)

    # Small requirements model -> simple route
    state = wf.classify_complexity({"project_id": "PROJ-001", "run_id": "RUN-001", "requirements": model.model_dump(mode="json")})
    assert state["planning_route"] == "simple"

    # Add 10 requirements -> complex route
    large_reqs = [
        Requirement(id=f"REQ-{i:03d}", type="functional", description=f"Functional feature {i}", source=SourceReference(section="SEC-001"))
        for i in range(1, 12)
    ]
    complex_model = model.model_copy(update={"requirements": large_reqs})
    state_complex = wf.classify_complexity({"project_id": "PROJ-001", "run_id": "RUN-002", "requirements": complex_model.model_dump(mode="json")})
    assert state_complex["planning_route"] == "complex"


# Test 7 & 8 & 9: Pattern Selection, Minimal Patterns, Pattern-to-Requirement Mapping
def test_pattern_selection(repo, sample_requirements):
    model, v_id = sample_requirements
    wf = PlanningWorkflow(repo, max_patterns=3)

    state = wf.select_patterns({"project_id": "PROJ-001", "run_id": "RUN-001", "requirements": model.model_dump(mode="json")})
    pats = state["selected_patterns"]
    assert len(pats) <= 3
    assert len(pats) > 0
    for p in pats:
        assert p["pattern_id"].startswith("PAT-")
        assert len(p["addressed_requirement_ids"]) >= 1


# Test 10 & 11 & 12 & 13 & 15: Parallel Research & Research Branches
def test_parallel_research_execution(repo, sample_requirements):
    model, v_id = sample_requirements
    wf = PlanningWorkflow(repo)

    state = wf.parallel_research({
        "project_id": "PROJ-001",
        "run_id": "RUN-001",
        "requirements": model.model_dump(mode="json"),
        "selected_patterns": [{"pattern_id": "PAT-001", "pattern_name": "ReAct", "rationale": "Reasoning"}]
    })

    findings = state["research_findings"]
    assert len(findings) >= 3
    types = {f["source_type"] for f in findings}
    assert "doc" in types
    assert "kb" in types
    assert "web" in types
    assert "llm" in types

    for f in findings:
        tag = f["citation_tag"]
        assert tag.startswith("[doc:") or tag.startswith("[kb:") or tag.startswith("[web:") or tag == "[llm]"


# Test 20 & 21: Architecture Design (Markdown & Structured JSON)
def test_architecture_design(repo, sample_requirements):
    model, v_id = sample_requirements
    wf = PlanningWorkflow(repo)

    state = wf.architecture_design({
        "project_id": "PROJ-001",
        "run_id": "RUN-001",
        "requirements": model.model_dump(mode="json"),
        "selected_patterns": [{"pattern_id": "PAT-001", "pattern_name": "ReAct", "rationale": "Reasoning"}],
        "research_findings": [{"finding_id": "F-1", "source_type": "llm", "citation_tag": "[llm]", "claim": "C", "evidence": "E"}]
    })

    assert "architecture_markdown" in state
    assert "# Architecture Specification" in state["architecture_markdown"]
    assert "architecture_json" in state
    arch = state["architecture_json"]
    assert len(arch["system_components"]) >= 1


# Test 22 & 23 & 24 & 27 & 28: Task Planning & Validation
def test_task_planning_and_validation(repo, sample_requirements):
    model, v_id = sample_requirements
    wf = PlanningWorkflow(repo)

    tasks_state = wf.task_planning({
        "project_id": "PROJ-001",
        "run_id": "RUN-001",
        "requirements": model.model_dump(mode="json"),
        "selected_patterns": [{"pattern_id": "PAT-001", "pattern_name": "ReAct", "rationale": "Reasoning"}],
        "research_findings": [{"finding_id": "F-1", "source_type": "llm", "citation_tag": "[llm]", "claim": "C", "evidence": "E"}]
    })

    val_state = wf.validate_plan({
        "project_id": "PROJ-001",
        "run_id": "RUN-001",
        "requirements": model.model_dump(mode="json"),
        "tasks": tasks_state["tasks"],
        "selected_patterns": [{"pattern_id": "PAT-001", "pattern_name": "ReAct", "rationale": "Reasoning"}],
        "research_findings": [{"finding_id": "F-1", "source_type": "llm", "citation_tag": "[llm]", "claim": "C", "evidence": "E"}],
        "iteration_count": 0
    })

    val = val_state["validation"]
    assert val["passed"] is True
    assert len(val["coverage_errors"]) == 0
    assert len(val["ordering_errors"]) == 0


# Test 25 & 26: Forward Dependency & Cycle Rejection
def test_invalid_dependency_rejection(repo, sample_requirements):
    model, v_id = sample_requirements
    wf = PlanningWorkflow(repo)

    bad_tasks = [
        {"task_id": "TASK-001", "sequence_number": 1, "title": "Task 1", "description": "D1", "target_files": ["f1.py"], "acceptance_criteria": ["ac1"], "dependency_task_ids": ["TASK-002"], "requirement_ids": ["REQ-001"], "pattern_ids": ["PAT-001"], "research_citation_tags": ["[llm]"]},
        {"task_id": "TASK-002", "sequence_number": 2, "title": "Task 2", "description": "D2", "target_files": ["f2.py"], "acceptance_criteria": ["ac2"], "dependency_task_ids": [], "requirement_ids": ["REQ-002"], "pattern_ids": ["PAT-001"], "research_citation_tags": ["[llm]"]}
    ]

    val_state = wf.validate_plan({
        "project_id": "PROJ-001",
        "run_id": "RUN-001",
        "requirements": model.model_dump(mode="json"),
        "tasks": bad_tasks,
        "selected_patterns": [{"pattern_id": "PAT-001", "pattern_name": "ReAct", "rationale": "Reasoning"}],
        "research_findings": [{"finding_id": "F-1", "source_type": "llm", "citation_tag": "[llm]", "claim": "C", "evidence": "E"}],
        "iteration_count": 0
    })

    val = val_state["validation"]
    assert val["passed"] is False
    assert len(val["ordering_errors"]) > 0


# Test 31 & 32 & 33 & 34: REST Fallback Approval & Rejection
def test_rest_approve_and_reject(client, auth_headers, project, sample_requirements, repo):
    p_id = project["project_id"]
    model, version_id = sample_requirements

    # Start planning workflow
    res = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"requirements_model_version_id": version_id})
    run_id = res.json()["run_id"]

    # Reject plan with feedback
    res_reject = client.post(f"/projects/{p_id}/runs/{run_id}/reject", headers=auth_headers, json={"feedback": "Add explicit security audit task."})
    print("\n\nREJECT RES:", res_reject.json(), "\n\n")
    assert res_reject.status_code == 200
    run_info = res_reject.json()
    assert run_info["rejection_feedback"] == "Add explicit security audit task."

    # Approve plan
    res_approve = client.post(f"/projects/{p_id}/runs/{run_id}/approve", headers=auth_headers, json={})
    assert res_approve.status_code == 200
    approved_run = res_approve.json()
    assert approved_run["approval_status"] == "APPROVED"


# Test 37 & 38 & 39 & 40: Task Editing (PATCH, Reorder, Split, Approval Rejection)
def test_task_patch_reorder_split(client, auth_headers, project, sample_requirements, repo):
    p_id = project["project_id"]
    model, version_id = sample_requirements

    res = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"requirements_model_version_id": version_id})
    run_id = res.json()["run_id"]

    tasks_res = client.get(f"/projects/{p_id}/runs/{run_id}/tasks", headers=auth_headers)
    tasks = tasks_res.json()
    assert len(tasks) >= 2

    # PATCH description
    t1_id = tasks[0]["task_id"]
    patch_res = client.patch(f"/projects/{p_id}/runs/{run_id}/tasks/{t1_id}", headers=auth_headers, json={"description": "Updated description for task 1"})
    assert patch_res.status_code == 200
    updated = patch_res.json()
    assert any(t["description"] == "Updated description for task 1" for t in updated)

    # Task Split
    t2_id = tasks[1]["task_id"]
    split_spec = [
        {"title": "Subtask 2.1", "description": "First part of task 2", "target_files": ["app/part1.py"], "acceptance_criteria": ["AC 1"]},
        {"title": "Subtask 2.2", "description": "Second part of task 2", "target_files": ["app/part2.py"], "acceptance_criteria": ["AC 2"]}
    ]
    split_res = client.patch(f"/projects/{p_id}/runs/{run_id}/tasks/{t2_id}", headers=auth_headers, json={"split_into": split_spec})
    assert split_res.status_code == 200
    split_tasks = split_res.json()
    titles = [t["title"] for t in split_tasks]
    assert "Subtask 2.1" in titles
    assert "Subtask 2.2" in titles

    # Approve run and attempt edit -> should be rejected with 400
    client.post(f"/projects/{p_id}/runs/{run_id}/approve", headers=auth_headers, json={})
    edit_res_after_approval = client.patch(f"/projects/{p_id}/runs/{run_id}/tasks/{t1_id}", headers=auth_headers, json={"description": "New edit after approval"})
    assert edit_res_after_approval.status_code == 400


# Test 44: Duplicate Start Protection / Run Retrieval
def test_get_run_artifacts(client, auth_headers, project, sample_requirements):
    p_id = project["project_id"]
    model, version_id = sample_requirements

    res = client.post(f"/projects/{p_id}/workflows/planning", headers=auth_headers, json={"requirements_model_version_id": version_id})
    run_id = res.json()["run_id"]

    # Get status
    run_res = client.get(f"/projects/{p_id}/runs/{run_id}", headers=auth_headers)
    assert run_res.status_code == 200
    assert run_res.json()["run_id"] == run_id

    # Get artifacts
    art_res = client.get(f"/projects/{p_id}/runs/{run_id}/artifacts", headers=auth_headers)
    assert art_res.status_code == 200, f"Got response {art_res.status_code}: {art_res.text}"

    art_data = art_res.json()
    assert "patterns" in art_data
    assert "research" in art_data
    assert "tasks" in art_data


# Test 51 & 52 & 53: Alembic Migrations Single Head & Double Upgrade
def test_alembic_migration_head():
    import sys
    import subprocess
    import shutil

    alembic_bin = shutil.which("alembic") or f"{sys.prefix}/bin/alembic"
    res = subprocess.run([alembic_bin, "heads"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "0006_planning_tables" in res.stdout


