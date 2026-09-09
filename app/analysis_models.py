from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from .models import RequirementsModel


IssueType = Literal["ambiguity", "gap", "conflict", "inconsistency"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AnalysisStatus = Literal["no_issues", "clarification_required"]


class AnalysisIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_id: str = Field(pattern=r"^(AMB|GAP|CON|INC)-[0-9]{3,}$")
    type: IssueType
    severity: Severity
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    affected_requirements: List[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    clarification_required: bool
    severity_reason: str = Field(min_length=1)


class ClarificationQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question_id: str = Field(pattern=r"^Q-[0-9]{3,}$")
    issue_id: str = Field(pattern=r"^(AMB|GAP|CON|INC)-[0-9]{3,}$")
    affected_requirements: List[str] = Field(default_factory=list)
    question: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    priority: Severity


class AnalysisSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    total_requirements_analyzed: int = Field(ge=0)
    ambiguities: int = Field(ge=0)
    gaps: int = Field(ge=0)
    conflicts: int = Field(ge=0)
    inconsistencies: int = Field(ge=0)
    clarification_questions: int = Field(ge=0)


class RequirementsAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brd_id: str = Field(min_length=1)
    analysis_id: str = Field(pattern=r"^ANALYSIS-[A-F0-9]{12}$")
    status: AnalysisStatus
    summary: AnalysisSummary
    issues: List[AnalysisIssue] = Field(default_factory=list)
    clarification_questions: List[ClarificationQuestion] = Field(default_factory=list)
    extraction_metadata: Dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_references_and_summary(self) -> "RequirementsAnalysis":
        requirement_ids = getattr(self, "_requirement_ids", set())
        issue_ids = [issue.issue_id for issue in self.issues]
        question_ids = [question.question_id for question in self.clarification_questions]
        if len(issue_ids) != len(set(issue_ids)):
            raise ValueError("issue IDs must be unique")
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question IDs must be unique")
        if self._references_bound:
            for issue in self.issues:
                missing = set(issue.affected_requirements) - requirement_ids
                if missing:
                    raise ValueError(f"issue {issue.issue_id} references unknown requirements: {sorted(missing)}")
        issue_map = {issue.issue_id: issue for issue in self.issues}
        for question in self.clarification_questions:
            if question.issue_id not in issue_map:
                raise ValueError(f"question {question.question_id} references unknown issue {question.issue_id}")
            if self._references_bound:
                missing = set(question.affected_requirements) - requirement_ids
                if missing:
                    raise ValueError(f"question {question.question_id} references unknown requirements: {sorted(missing)}")
        expected = {
            "ambiguities": sum(issue.type == "ambiguity" for issue in self.issues),
            "gaps": sum(issue.type == "gap" for issue in self.issues),
            "conflicts": sum(issue.type == "conflict" for issue in self.issues),
            "inconsistencies": sum(issue.type == "inconsistency" for issue in self.issues),
            "clarification_questions": len(self.clarification_questions),
        }
        for field, value in expected.items():
            if getattr(self.summary, field) != value:
                raise ValueError(f"summary.{field} does not match the returned findings")
        if self._references_bound and self.summary.total_requirements_analyzed != len(requirement_ids):
            raise ValueError("summary.total_requirements_analyzed does not match the input Requirements Model")
        if self.status == "no_issues" and self.issues:
            raise ValueError("no_issues status cannot contain issues")
        if self.clarification_questions and self.status != "clarification_required":
            raise ValueError("clarification questions require clarification_required status")
        return self

    @classmethod
    def from_payload(cls, payload: dict, requirements: RequirementsModel) -> "RequirementsAnalysis":
        instance = cls.model_validate(payload)
        object.__setattr__(instance, "_requirement_ids", {item.id for item in requirements.requirements})
        object.__setattr__(instance, "_references_bound", True)
        instance.validate_references_and_summary()
        return instance

    _requirement_ids: set[str] = PrivateAttr(default_factory=set)
    _references_bound: bool = PrivateAttr(default=False)
