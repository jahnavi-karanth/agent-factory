from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


RequirementType = Literal["functional", "non_functional", "business_rule", "constraint", "data", "other"]


class SourceReference(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: str | None = None
    title: str | None = None
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)


class Requirement(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^REQ-[0-9]{3,}$")
    type: RequirementType
    description: str = Field(min_length=1)
    source: SourceReference
    priority: str | None = None


class RequirementsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brd_id: str = Field(min_length=1)
    title: str | None = None
    source_filename: str = Field(min_length=1)
    business_problem: str | None = None
    business_objectives: list[str] = Field(default_factory=list)
    stakeholders: list[str] = Field(default_factory=list)
    user_roles: list[str] = Field(default_factory=list)
    requirements: list[Requirement] = Field(default_factory=list)
    non_functional_requirements: list[str] = Field(default_factory=list)
    business_rules: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    data_requirements: list[str] = Field(default_factory=list)
    external_dependencies: list[str] = Field(default_factory=list)
    success_criteria: list[str] = Field(default_factory=list)
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("requirements")
    @classmethod
    def unique_requirement_ids(cls, value: list[Requirement]) -> list[Requirement]:
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
