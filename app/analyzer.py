from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict, Optional

from .analysis_models import RequirementsAnalysis
from .llm import ExtractionError, GeminiExtractor
from .models import RequirementsModel

logger = logging.getLogger(__name__)

ANALYSIS_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "required": ["issues", "clarification_questions"],
    "properties": {
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["issue_id", "type", "severity", "title", "description", "affected_requirements", "reason", "clarification_required", "severity_reason"],
                "properties": {
                    "issue_id": {"type": "string"},
                    "type": {"type": "string", "enum": ["ambiguity", "gap", "conflict", "inconsistency"]},
                    "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "affected_requirements": {"type": "array", "items": {"type": "string"}},
                    "reason": {"type": "string"},
                    "clarification_required": {"type": "boolean"},
                    "severity_reason": {"type": "string"},
                },
            },
        },
        "clarification_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["question_id", "issue_id", "affected_requirements", "question", "reason", "priority"],
                "properties": {
                    "question_id": {"type": "string", "pattern": "^Q-[0-9]{3,}$"},
                    "issue_id": {"type": "string"},
                    "affected_requirements": {"type": "array", "items": {"type": "string"}},
                    "question": {"type": "string"},
                    "reason": {"type": "string"},
                    "priority": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                },
            },
        },
    },
}


class RequirementsAnalyzer:
    def __init__(self, extractor: Optional[GeminiExtractor] = None):
        self.extractor = extractor or GeminiExtractor()

    def analyze(self, requirements: RequirementsModel) -> RequirementsAnalysis:
        logger.info("requirements analysis started brd_id=%s", requirements.brd_id)
        prompt = self._build_prompt(requirements)
        raw = self.extractor.generate_json(prompt, ANALYSIS_SCHEMA)
        if not raw:
            raise ExtractionError("the analysis extractor returned an empty response")
        payload = dict(raw)
        payload["clarification_questions"] = [self._normalize_question(item) for item in payload.get("clarification_questions", [])]
        payload.update({
            "brd_id": requirements.brd_id,
            "analysis_id": self._analysis_id(requirements),
            "status": "clarification_required" if payload.get("issues") or payload.get("clarification_questions") else "no_issues",
            "summary": self._summary(payload, requirements),
            "extraction_metadata": {"milestone": "2", "provider": "gemini"},
        })
        try:
            result = RequirementsAnalysis.from_payload(payload, requirements)
        except Exception as exc:
            raise ExtractionError(f"invalid Requirements Analysis from extractor: {exc}") from exc
        logger.info("requirements analysis completed brd_id=%s issues=%d", requirements.brd_id, len(result.issues))
        return result

    @staticmethod
    def _normalize_question(question: Any) -> Any:
        if not isinstance(question, dict):
            return question
        normalized = dict(question)
        question_id = normalized.get("question_id")
        if isinstance(question_id, str) and question_id.upper().startswith("QST-"):
            normalized["question_id"] = "Q-" + question_id[4:]
        return normalized

    @staticmethod
    def _analysis_id(requirements: RequirementsModel) -> str:
        digest = hashlib.sha256(requirements.model_dump_json().encode("utf-8")).hexdigest()[:12].upper()
        return f"ANALYSIS-{digest}"

    @staticmethod
    def _summary(payload: Dict[str, Any], requirements: RequirementsModel) -> Dict[str, int]:
        issues = payload.get("issues") if isinstance(payload.get("issues"), list) else []
        questions = payload.get("clarification_questions") if isinstance(payload.get("clarification_questions"), list) else []
        return {
            "total_requirements_analyzed": len(requirements.requirements),
            "ambiguities": sum(isinstance(i, dict) and i.get("type") == "ambiguity" for i in issues),
            "gaps": sum(isinstance(i, dict) and i.get("type") == "gap" for i in issues),
            "conflicts": sum(isinstance(i, dict) and i.get("type") == "conflict" for i in issues),
            "inconsistencies": sum(isinstance(i, dict) and i.get("type") == "inconsistency" for i in issues),
            "clarification_questions": len(questions),
        }

    @staticmethod
    def _build_prompt(requirements: RequirementsModel) -> str:
        model_json = requirements.model_dump_json(indent=2)
        return f"""Analyze only the supplied Requirements Model. Do not re-parse an original BRD and do not invent requirements, actors, policies, SLAs, time limits, workflows, integrations, security controls, retention policies, technical decisions, or answers. Preserve every existing requirement ID exactly. Identify only meaningful, material ambiguity, missing information/gaps, genuine conflicts, and meaningful inconsistencies that could affect business behavior, architecture, data, security, integrations, workflows, APIs, testing, or implementation. Do not flag writing style. Do not silently resolve any issue. For each issue provide a unique prefixed issue_id (AMB-, GAP-, CON-, or INC-), type, severity (LOW, MEDIUM, HIGH, or CRITICAL), title, description, affected requirement IDs, reason, severity_reason, and clarification_required. For each question use the exact question_id format Q-001, Q-002, ... . Generate a neutral clarification question only when the issue materially affects implementation/design and cannot be derived from the model. Questions must not suggest an answer or introduce thresholds, actors, workflows, or policies. Use empty arrays when no findings exist.\n\nREQUIREMENTS MODEL:\n{model_json}"""
