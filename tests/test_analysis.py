from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.analysis_models import RequirementsAnalysis
from app.analyzer import RequirementsAnalyzer
from app.llm import ExtractionError
from app.main import create_app
from app.models import RequirementsModel


def requirements_model():
    return RequirementsModel(
        brd_id="BRD-TEST12345678",
        title="Generic Platform",
        source_filename="generic.md",
        requirements=[
            {"id": "REQ-001", "type": "functional", "description": "Users can submit a request.", "source": {}},
            {"id": "REQ-002", "type": "functional", "description": "The system sends appropriate notifications.", "source": {}},
            {"id": "REQ-003", "type": "functional", "description": "Requests are reviewed by an authorized reviewer.", "source": {}},
        ],
    )


def analysis_payload():
    return {
        "issues": [
            {
                "issue_id": "AMB-001", "type": "ambiguity", "severity": "HIGH", "title": "Notification behavior is undefined",
                "description": "The notification requirement does not define events, recipients, channels, or timing.",
                "affected_requirements": ["REQ-002"], "reason": "Different interpretations would change workflow and integration design.",
                "clarification_required": True, "severity_reason": "It affects workflow and integrations.",
            },
            {
                "issue_id": "GAP-001", "type": "gap", "severity": "HIGH", "title": "Reviewer authorization is underspecified",
                "description": "The model does not define how reviewer authorization is determined.",
                "affected_requirements": ["REQ-003"], "reason": "Authorization behavior cannot be implemented reliably.",
                "clarification_required": True, "severity_reason": "It affects security and workflow design.",
            },
        ],
        "clarification_questions": [
            {
                "question_id": "Q-001", "issue_id": "AMB-001", "affected_requirements": ["REQ-002"],
                "question": "Which events should trigger notifications, who should receive them, and through which channels?",
                "reason": "The notification behavior is not defined in the Requirements Model.", "priority": "HIGH",
            },
            {
                "question_id": "Q-002", "issue_id": "GAP-001", "affected_requirements": ["REQ-003"],
                "question": "What rules determine whether a user is authorized to review a request?",
                "reason": "The authorization decision is not defined in the Requirements Model.", "priority": "HIGH",
            },
        ],
    }


class FakeAnalysisExtractor:
    def generate_json(self, prompt, schema):
        assert "REQ-001" in prompt
        assert "do not invent" in prompt.lower()
        return analysis_payload()


def test_analysis_returns_structured_findings_and_neutral_questions():
    result = RequirementsAnalyzer(FakeAnalysisExtractor()).analyze(requirements_model())
    assert result.status == "clarification_required"
    assert result.summary.total_requirements_analyzed == 3
    assert result.summary.ambiguities == 1
    assert result.summary.gaps == 1
    assert result.summary.conflicts == 0
    assert result.clarification_questions[0].question.startswith("Which events")


def test_analysis_endpoint_consumes_requirements_model_directly():
    app = create_app(analyzer=RequirementsAnalyzer(FakeAnalysisExtractor()))
    response = TestClient(app).post("/api/requirements/analyze", json=requirements_model().model_dump(mode="json"))
    assert response.status_code == 200
    assert response.json()["summary"]["total_requirements_analyzed"] == 3


def test_clear_model_can_have_no_issues():
    class ClearExtractor:
        def generate_json(self, prompt, schema):
            return {"issues": [], "clarification_questions": []}

    result = RequirementsAnalyzer(ClearExtractor()).analyze(requirements_model())
    assert result.status == "no_issues"
    assert result.summary.clarification_questions == 0


def test_conflict_payload_is_supported():
    payload = analysis_payload()
    payload["issues"] = [{
        "issue_id": "CON-001", "type": "conflict", "severity": "CRITICAL", "title": "Conflicting approval rules",
        "description": "Two requirements assign incompatible approval responsibilities.", "affected_requirements": ["REQ-001", "REQ-003"],
        "reason": "The workflow cannot be implemented without choosing a rule.", "clarification_required": True,
        "severity_reason": "It changes the core workflow.",
    }]
    payload["clarification_questions"] = [{
        "question_id": "Q-001", "issue_id": "CON-001", "affected_requirements": ["REQ-001", "REQ-003"],
        "question": "Which approval responsibility should govern the workflow?", "reason": "The requirements conflict.", "priority": "CRITICAL",
    }]
    class ConflictExtractor:
        def generate_json(self, prompt, schema):
            return payload
    result = RequirementsAnalyzer(ConflictExtractor()).analyze(requirements_model())
    assert result.summary.conflicts == 1


def test_unknown_requirement_reference_is_rejected():
    payload = analysis_payload()
    payload["issues"][0]["affected_requirements"] = ["REQ-999"]
    class InvalidExtractor:
        def generate_json(self, prompt, schema):
            return payload
    try:
        RequirementsAnalyzer(InvalidExtractor()).analyze(requirements_model())
        raise AssertionError("expected invalid reference failure")
    except ExtractionError as exc:
        assert "unknown requirements" in str(exc)


def test_malformed_analysis_is_rejected():
    class MalformedExtractor:
        def generate_json(self, prompt, schema):
            return {"issues": "not-an-array", "clarification_questions": []}
    try:
        RequirementsAnalyzer(MalformedExtractor()).analyze(requirements_model())
        raise AssertionError("expected malformed output failure")
    except ExtractionError:
        pass


def test_empty_issue_object_is_rejected():
    class EmptyIssueExtractor:
        def generate_json(self, prompt, schema):
            return {"issues": [{}], "clarification_questions": []}
    try:
        RequirementsAnalyzer(EmptyIssueExtractor()).analyze(requirements_model())
        raise AssertionError("expected empty issue failure")
    except ExtractionError as exc:
        assert "issue_id" in str(exc)


def test_analysis_provider_failure_is_propagated():
    class BrokenExtractor:
        def generate_json(self, prompt, schema):
            raise ExtractionError("provider unavailable")
    try:
        RequirementsAnalyzer(BrokenExtractor()).analyze(requirements_model())
        raise AssertionError("expected provider failure")
    except ExtractionError as exc:
        assert "provider unavailable" in str(exc)
