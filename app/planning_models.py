from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class PlanningWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    document_ids: List[str] = Field(default_factory=list)
    requirements_model_version_id: Optional[int] = None
    brd_id: Optional[str] = None


class ComplexityClassification(BaseModel):
    model_config = ConfigDict(extra="allow")

    complexity: Literal["simple", "complex"] = "simple"
    reasoning: str = ""
    functional_req_count: int = 0
    non_functional_req_count: int = 0
    integration_count: int = 0


class SelectedPattern(BaseModel):
    model_config = ConfigDict(extra="allow")

    pattern_id: str
    pattern_name: str
    rationale: str
    addressed_requirement_ids: List[str] = Field(default_factory=list)
    evidence: Optional[str] = None
    confidence: float = 1.0


class ResearchFinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    finding_id: str
    source_type: Literal["doc", "kb", "web", "llm"]
    citation_tag: str
    claim: str
    evidence: str
    source_url: Optional[str] = None
    document_id: Optional[str] = None
    section_id: Optional[str] = None
    pattern_id: Optional[str] = None
    confidence: float = 1.0


class ArchitectureComponent(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    responsibility: str
    requirement_ids: List[str] = Field(default_factory=list)
    pattern_ids: List[str] = Field(default_factory=list)
    research_citation_tags: List[str] = Field(default_factory=list)


class DataFlow(BaseModel):
    model_config = ConfigDict(extra="allow")

    from_component: str
    to_component: str
    description: str
    requirement_ids: List[str] = Field(default_factory=list)


class AgentNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_name: str
    role: str
    pattern_id: Optional[str] = None


class ToolDefinition(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str


class RiskItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    category: str
    risk: str
    mitigation: str


class ArchitectureDocument(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    requirements_model_version_id: int
    selected_pattern_ids: List[str] = Field(default_factory=list)
    system_components: List[ArchitectureComponent] = Field(default_factory=list)
    data_flows: List[DataFlow] = Field(default_factory=list)
    agent_topology: List[AgentNode] = Field(default_factory=list)
    tools: List[ToolDefinition] = Field(default_factory=list)
    deployment: Dict[str, Any] = Field(default_factory=dict)
    risks: List[RiskItem] = Field(default_factory=list)
    traceability: Dict[str, Any] = Field(default_factory=dict)


class PlanningTask(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    sequence_number: int
    title: str
    description: str
    target_files: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    dependency_task_ids: List[str] = Field(default_factory=list)
    requirement_ids: List[str] = Field(default_factory=list)
    pattern_ids: List[str] = Field(default_factory=list)
    research_citation_tags: List[str] = Field(default_factory=list)
    status: str = "PLANNED"


class TaskSplitSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str
    description: str
    target_files: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    requirement_ids: List[str] = Field(default_factory=list)
    pattern_ids: List[str] = Field(default_factory=list)
    research_citation_tags: List[str] = Field(default_factory=list)


class TaskPatchRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: Optional[str] = None
    description: Optional[str] = None
    sequence_number: Optional[int] = None
    target_files: Optional[List[str]] = None
    acceptance_criteria: Optional[List[str]] = None
    dependency_task_ids: Optional[List[str]] = None
    split_into: Optional[List[TaskSplitSpec]] = None


class ValidationResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    passed: bool
    coverage_errors: List[str] = Field(default_factory=list)
    ordering_errors: List[str] = Field(default_factory=list)
    pattern_fidelity_errors: List[str] = Field(default_factory=list)
    atomicity_errors: List[str] = Field(default_factory=list)
    architecture_consistency_errors: List[str] = Field(default_factory=list)
    citation_errors: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class RejectionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    feedback: Optional[str] = ""


