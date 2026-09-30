from __future__ import annotations

import os
import shutil
import tempfile
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.pattern_models import PatternCreateRequest, PatternSearchRequest, PatternUpdateRequest
from app.pattern_service import PatternService
from app.repository import SQLiteRepository
from app.document_store import DocumentStore


@pytest.fixture
def temp_dir():
    dirpath = tempfile.mkdtemp()
    yield dirpath
    shutil.rmtree(dirpath, ignore_errors=True)


@pytest.fixture
def test_repo(temp_dir):
    db_path = os.path.join(temp_dir, "test_factory.sqlite3")
    repo = SQLiteRepository(path=db_path)
    return repo


@pytest.fixture
def test_doc_store(temp_dir):
    chroma_path = os.path.join(temp_dir, "chroma")
    doc_store = DocumentStore(path=chroma_path)
    return doc_store


@pytest.fixture
def pattern_service(test_repo, test_doc_store):
    svc = PatternService(repository=test_repo, document_store=test_doc_store)
    return svc


@pytest.fixture
def client(test_repo, test_doc_store, pattern_service):
    app = create_app(
        repository=test_repo,
        document_store=test_doc_store,
        pattern_service=pattern_service,
    )
    test_client = TestClient(app)
    registration = test_client.post("/auth/register", json={"email": "patterns@example.com", "password": "password123"})
    test_client.headers.update({"Authorization": f"Bearer {registration.json()['access_token']}"})
    return test_client


def test_seed_initial_patterns(pattern_service, test_repo, test_doc_store):
    seeded = pattern_service.seed_initial_patterns()
    assert len(seeded) >= 10
    
    # Verify canonical patterns are seeded
    names = {p.name for p in seeded}
    assert "ReAct" in names
    assert "Planner-Executor" in names
    assert "Multi-Agent Debate" in names

    # Test idempotency (seeding again shouldn't duplicate)
    seeded_again = pattern_service.seed_initial_patterns()
    assert len(seeded_again) == len(seeded)
    
    all_db = test_repo.list_patterns()
    assert len(all_db) == len(seeded)


def test_pattern_crud_endpoints(client):
    # 1. Create a pattern
    create_payload = {
        "id": "PAT-TEST-001",
        "name": "Custom Test Pattern",
        "intent": "Test pattern creation and CRUD operations",
        "structure": "Step 1: Input -> Step 2: Process -> Step 3: Output",
        "when_to_use": ["In unit tests", "During validation"],
        "when_not_to_use": ["In production without review"],
        "prerequisites": ["Python 3.12"],
        "references": ["https://example.com/pattern"],
        "tags": ["test", "custom"],
        "description": "A custom pattern created for test suite validation",
        "strengths": "Fast and deterministic",
        "weaknesses": "Only for testing",
    }
    res = client.post("/patterns", json=create_payload)
    assert res.status_code == 201
    data = res.json()
    assert data["id"] == "PAT-TEST-001"
    assert data["name"] == "Custom Test Pattern"
    assert data["tags"] == ["test", "custom"]

    # 2. Get pattern by ID
    res = client.get("/patterns/PAT-TEST-001")
    assert res.status_code == 200
    assert res.json()["name"] == "Custom Test Pattern"

    # 3. List patterns (with tag filter)
    res = client.get("/patterns?tag=custom")
    assert res.status_code == 200
    listed = res.json()
    assert len(listed) == 1
    assert listed[0]["id"] == "PAT-TEST-001"

    # 4. Patch pattern
    patch_payload = {
        "description": "Updated description for test pattern",
        "tags": ["test", "custom", "updated"],
    }
    res = client.patch("/patterns/PAT-TEST-001", json=patch_payload)
    assert res.status_code == 200
    patched = res.json()
    assert patched["description"] == "Updated description for test pattern"
    assert "updated" in patched["tags"]

    # 5. Delete pattern
    res = client.delete("/patterns/PAT-TEST-001")
    assert res.status_code == 200
    assert res.json()["id"] == "PAT-TEST-001"

    # 6. Verify 404 after deletion
    res = client.get("/patterns/PAT-TEST-001")
    assert res.status_code == 404


def test_bulk_create_patterns(client):
    items = [
        {
            "name": "Bulk Pattern 1",
            "intent": "Intent for bulk pattern 1",
            "structure": "Structure 1",
            "when_to_use": ["Case A"],
        },
        {
            "name": "Bulk Pattern 2",
            "intent": "Intent for bulk pattern 2",
            "structure": "Structure 2",
            "when_to_use": ["Case B"],
        },
    ]
    res = client.post("/patterns/bulk", json=items)
    assert res.status_code == 201
    created = res.json()
    assert len(created) == 2
    assert created[0]["name"] == "Bulk Pattern 1"
    assert created[1]["name"] == "Bulk Pattern 2"


def test_pattern_semantic_search(client, pattern_service):
    # Ensure patterns are seeded
    pattern_service.seed_initial_patterns()

    # Perform semantic search for reasoning and tool use
    search_payload = {
        "query": "iterative reasoning execution with external tools",
        "top_k": 3,
    }
    res = client.post("/patterns/search", json=search_payload)
    assert res.status_code == 200
    results = res.json()
    assert len(results) > 0
    assert "pattern_id" in results[0]
    assert "score" in results[0]
    assert "matched_fields" in results[0]
    assert "pattern" in results[0]


def test_pattern_search_with_tag_filtering(client, pattern_service):
    pattern_service.seed_initial_patterns()

    # Search with tag filter "multi-agent"
    search_payload = {
        "query": "debate consensus decision making",
        "tags": ["multi-agent"],
        "top_k": 5,
    }
    res = client.post("/patterns/search", json=search_payload)
    assert res.status_code == 200
    results = res.json()
    for item in results:
        pattern_tags = item["pattern"]["tags"]
        assert "multi-agent" in pattern_tags


def test_stale_vector_cleanup_on_search(client, pattern_service, test_repo, test_doc_store):
    pattern_service.seed_initial_patterns()

    # Manually delete a pattern from SQLite directly without calling delete_pattern
    patterns = test_repo.list_patterns()
    deleted_p = patterns[0]
    test_repo.delete_pattern(deleted_p["id"])

    # Perform search; search_patterns should filter out the deleted pattern and clean vector
    res = client.post("/patterns/search", json={"query": "pattern reasoning", "top_k": 10})
    assert res.status_code == 200
    returned_ids = {r["pattern_id"] for r in res.json()}
    assert deleted_p["id"] not in returned_ids
