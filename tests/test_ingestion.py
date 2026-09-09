from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.parser import parse_document
from app.service import IngestionService


FIXTURE = Path(__file__).parents[1] / "Business Requirements Document — Corporate Expense Management Platform.md"


class FakeExtractor:
    def extract(self, document):
        assert "Corporate Expense" in document.text
        return {
            "title": "Corporate Expense Management Platform",
            "business_problem": "The current process relies on spreadsheets and email.",
            "business_objectives": ["Replace the current process."],
            "stakeholders": ["Employees", "Managers"],
            "user_roles": ["Employee", "Manager"],
            "requirements": [
                {"id": "REQ-001", "type": "functional", "description": "Users can submit a BRD-independent request.", "source": {"section": "7.1", "title": "User Access"}, "priority": None},
                {"id": "REQ-002", "type": "non_functional", "description": "Access must be authorized.", "source": {"section": "7.1", "title": "User Access"}, "priority": None},
            ],
            "non_functional_requirements": ["Authorized access."],
            "business_rules": [],
            "constraints": [],
            "assumptions": [],
            "data_requirements": [],
            "external_dependencies": [],
            "success_criteria": [],
        }


def client():
    return TestClient(create_app(IngestionService(FakeExtractor())))


def test_health():
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json()["milestone"] == "BRD ingestion"


def test_upload_fixture_returns_structured_model():
    with FIXTURE.open("rb") as stream:
        response = client().post("/api/brd/upload", files={"file": (FIXTURE.name, stream, "text/markdown")})
    assert response.status_code == 200
    body = response.json()
    assert body["brd_id"].startswith("BRD-")
    assert body["source_filename"] == FIXTURE.name
    assert [item["id"] for item in body["requirements"]] == ["REQ-001", "REQ-002"]
    assert body["requirements"][0]["source"]["section"] == "7.1"


def test_upload_is_generic_for_another_markdown_document():
    app = create_app(IngestionService(type("GenericExtractor", (), {"extract": lambda self, document: {
        "title": "A different product", "business_problem": "A different problem", "business_objectives": [],
        "stakeholders": [], "user_roles": [], "requirements": [{"id": "REQ-001", "type": "other", "description": "The product shall work.", "source": {}, "priority": None}],
        "non_functional_requirements": [], "business_rules": [], "constraints": [], "assumptions": [], "data_requirements": [], "external_dependencies": [], "success_criteria": [],
    }})()))
    response = TestClient(app).post("/api/brd/upload", files={"file": ("other.md", b"# Other\n\nA different product.", "text/markdown")})
    assert response.status_code == 200
    assert response.json()["title"] == "A different product"


def test_rejects_unsupported_format():
    response = client().post("/api/brd/upload", files={"file": ("brief.pdf", b"not really pdf", "application/pdf")})
    assert response.status_code == 400
    assert "unsupported BRD format" in response.json()["detail"]


def test_rejects_empty_file():
    response = client().post("/api/brd/upload", files={"file": ("empty.md", b"", "text/markdown")})
    assert response.status_code == 400
    assert "empty" in response.json()["detail"]


def test_extractor_failure_is_structured():
    class BrokenExtractor:
        def extract(self, document):
            from app.llm import ExtractionError
            raise ExtractionError("provider unavailable")

    response = TestClient(create_app(IngestionService(BrokenExtractor()))).post("/api/brd/upload", files={"file": ("brief.md", b"# Brief\ntext", "text/markdown")})
    assert response.status_code == 502
    assert response.json()["error"] == "brd_ingestion_failed"


def test_model_rejects_duplicate_or_nonsequential_ids():
    from pydantic import ValidationError
    from app.models import RequirementsModel
    try:
        RequirementsModel(brd_id="BRD-x", source_filename="x.md", requirements=[
            {"id": "REQ-001", "type": "other", "description": "one", "source": {}},
            {"id": "REQ-001", "type": "other", "description": "two", "source": {}},
        ])
        raise AssertionError("expected validation error")
    except ValidationError:
        pass


def test_normalizes_title_cased_requirement_types():
    document = parse_document("generic.md", b"# Generic BRD\nThe system shall work.")
    raw = {
        "title": "Generic BRD",
        "requirements": [{"id": "REQ-001", "type": "Functional", "description": "The system shall work.", "source": {}, "priority": None}],
    }
    model = IngestionService._validate_and_enrich(raw, document)
    assert model.requirements[0].type == "functional"


def test_preserves_unknown_requirement_type_as_other():
    document = parse_document("generic.md", b"# Generic BRD\nThe product should be easy to use.")
    raw = {
        "title": "Generic BRD",
        "requirements": [{"id": "REQ-001", "type": "user_experience", "description": "The product should be easy to use.", "source": {}, "priority": None}],
    }
    model = IngestionService._validate_and_enrich(raw, document)
    assert model.requirements[0].type == "other"
    assert "original_type" not in model.requirements[0].model_dump()


def test_source_title_must_match_a_real_document_heading():
    document = parse_document("generic.md", b"# Generic BRD\n\n## 2. Goals\nThe system shall work.")
    raw = {
        "title": "Generic BRD",
        "requirements": [{"id": "REQ-001", "type": "functional", "description": "The system shall work.", "source": {"title": "invented section", "section": "99"}, "priority": None}],
    }
    model = IngestionService._validate_and_enrich(raw, document)
    assert model.requirements[0].source.title is None
    assert model.requirements[0].source.section is None


def test_parser_normalizes_markdown_and_tracks_headings():
    document = parse_document("test.md", b"# Title\r\n\r\n## Section\r\nBody")
    assert document.text == "# Title\n\n## Section\nBody"
    assert document.headings == ((1, "Title", 1), (2, "Section", 3))
