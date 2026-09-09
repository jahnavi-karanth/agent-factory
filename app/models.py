from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


RequirementType = Literal["functional", "non_functional", "business_rule", "constraint", "data", "other"]


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: Optional[str] = None
    title: Optional[str] = None
    line_start: Optional[int] = Field(default=None, ge=1)
    line_end: Optional[int] = Field(default=None, ge=1)


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^REQ-[0-9]{3,}$")
    type: RequirementType
    description: str = Field(min_length=1)
    source: SourceReference
    priority: Optional[str] = None
    original_type: Optional[str] = None


class RequirementsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brd_id: str = Field(min_length=1)
    title: Optional[str] = None
    source_filename: str = Field(min_length=1)
    business_problem: Optional[str] = None
    business_objectives: List[str] = Field(default_factory=list)
    stakeholders: List[str] = Field(default_factory=list)
    user_roles: List[str] = Field(default_factory=list)
    requirements: List[Requirement] = Field(default_factory=list)
    non_functional_requirements: List[str] = Field(default_factory=list)
    business_rules: List[str] = Field(default_factory=list)
    constraints: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    data_requirements: List[str] = Field(default_factory=list)
    external_dependencies: List[str] = Field(default_factory=list)
    success_criteria: List[str] = Field(default_factory=list)
    extraction_metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("requirements")
    @classmethod
    def unique_requirement_ids(cls, value: List[Requirement]) -> List[Requirement]:
        ids = [item.id for item in value]
        if len(ids) != len(set(ids)):
            raise ValueError("requirement IDs must be unique")
        expected = [f"REQ-{index:03d}" for index in range(1, len(ids) + 1)]
        if ids != expected:
            raise ValueError("requirement IDs must be sequential and stable, starting at REQ-001")
        return value


class ErrorResponse(BaseModel):
    error: str
    detail: str


class HealthResponse(BaseModel):
    status: str
    milestone: str
