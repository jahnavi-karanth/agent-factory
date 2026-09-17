from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field, field_validator


class PatternModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: Optional[str] = None
    name: str = Field(..., min_length=1, description="Unique pattern name")
    intent: str = Field(..., min_length=1, description="Primary problem solved by this pattern")
    structure: Union[List[str], str] = Field(..., description="Structural steps or component flow")
    when_to_use: List[str] = Field(default_factory=list, description="Appropriate usage scenarios")
    when_not_to_use: List[str] = Field(default_factory=list, description="Inappropriate usage scenarios")
    prerequisites: List[str] = Field(default_factory=list, description="Required capabilities or tools")
    references: List[str] = Field(default_factory=list, description="Source references or papers")
    tags: List[str] = Field(default_factory=list, description="Search tags")
    description: Optional[str] = None
    strengths: Optional[Union[List[str], str]] = None
    weaknesses: Optional[Union[List[str], str]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PatternCreateRequest(BaseModel):
    id: Optional[str] = None
    name: str = Field(..., min_length=1)
    intent: str = Field(..., min_length=1)
    structure: Union[List[str], str]
    when_to_use: List[str] = Field(default_factory=list)
    when_not_to_use: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    references: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    description: Optional[str] = None
    strengths: Optional[Union[List[str], str]] = None
    weaknesses: Optional[Union[List[str], str]] = None


class PatternUpdateRequest(BaseModel):
    name: Optional[str] = None
    intent: Optional[str] = None
    structure: Optional[Union[List[str], str]] = None
    when_to_use: Optional[List[str]] = None
    when_not_to_use: Optional[List[str]] = None
    prerequisites: Optional[List[str]] = None
    references: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    description: Optional[str] = None
    strengths: Optional[Union[List[str], str]] = None
    weaknesses: Optional[Union[List[str], str]] = None


class PatternSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Search query text")
    tags: Optional[List[str]] = None
    top_k: int = Field(default=8, ge=1, le=50, description="Number of results to return (1-50)")

    @field_validator("query")
    @classmethod
    def validate_query(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("Query string cannot be empty or whitespace only")
        return value.strip()


class PatternSearchResult(BaseModel):
    pattern_id: str
    name: str
    score: float
    matched_fields: Dict[str, Any]
    pattern: PatternModel
