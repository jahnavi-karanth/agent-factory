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
        payload["issues"] = [normalized for item in self._as_list(payload.get("issues")) if (normalized := self._normalize_issue(item)) is not None]
        payload["clarification_questions"] = [normalized for item in self._as_list(payload.get("clarification_questions")) if (normalized := self._normalize_question(item)) is not None]
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
    def _as_list(value: Any) -> list:
        return value if isinstance(value, list) else []

    @staticmethod
    def _normalize_issue(issue: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(issue, dict):
            return None
        normalized = dict(issue)
        if not any(value not in (None, "", [], {}) for value in normalized.values()):
            return None
        normalized["issue_id"] = normalized.get("issue_id") or normalized.get("issueId") or normalized.get("id")
        raw_type = normalized.get("type") or normalized.get("issue_type") or "gap"
        type_key = str(raw_type).strip().lower().replace("-", "_").replace(" ", "_")
        type_aliases = {"missing": "gap", "missing_information": "gap", "contradiction": "conflict", "inconsistency": "inconsistency", "ambiguous": "ambiguity"}
        normalized["type"] = type_aliases.get(type_key, type_key)
        normalized["severity"] = str(normalized.get("severity") or "MEDIUM").strip().upper()
        normalized["title"] = normalized.get("title") or normalized.get("name") or "Requirement analysis issue"
        normalized["description"] = normalized.get("description") or normalized.get("details") or normalized["title"]
        normalized["reason"] = normalized.get("reason") or normalized.get("rationale") or normalized["description"]
        normalized["severity_reason"] = normalized.get("severity_reason") or normalized["reason"]
        normalized["affected_requirements"] = RequirementsAnalyzer._requirements_list(normalized.get("affected_requirements", normalized.get("affectedRequirements", [])))
        normalized["clarification_required"] = bool(normalized.get("clarification_required", normalized.get("clarificationRequired", True)))
        if isinstance(normalized.get("issue_id"), str):
            issue_id = normalized["issue_id"].upper()
            if issue_id.startswith("ISS-"):
                prefix = {"ambiguity": "AMB", "gap": "GAP", "conflict": "CON", "inconsistency": "INC"}.get(normalized["type"], "GAP")
                normalized["issue_id"] = prefix + issue_id[3:]
        return {key: normalized[key] for key in ("issue_id", "type", "severity", "title", "description", "affected_requirements", "reason", "clarification_required", "severity_reason")}

    @staticmethod
    def _requirements_list(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []

    @staticmethod
    def _normalize_question(question: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(question, dict):
            return None
        normalized = dict(question)
        if not any(value not in (None, "", [], {}) for value in normalized.values()):
            return None
        normalized["question_id"] = normalized.get("question_id") or normalized.get("questionId") or normalized.get("id")
        question_id = normalized.get("question_id")
        if isinstance(question_id, str):
            upper_id = question_id.upper()
            if upper_id.startswith("QST-"):
                normalized["question_id"] = "Q-" + question_id[4:]
            elif upper_id.startswith("QUESTION-"):
                normalized["question_id"] = "Q-" + question_id[9:]
        normalized["issue_id"] = normalized.get("issue_id") or normalized.get("issueId") or ""
        normalized["affected_requirements"] = RequirementsAnalyzer._requirements_list(normalized.get("affected_requirements", normalized.get("affectedRequirements", [])))
        normalized["question"] = normalized.get("question") or normalized.get("clarification_question") or normalized.get("text") or "What clarification is required for this issue?"
        normalized["reason"] = normalized.get("reason") or normalized.get("rationale") or "The Requirements Model does not resolve this issue."
        normalized["priority"] = str(normalized.get("priority") or "MEDIUM").strip().upper()
        return {key: normalized[key] for key in ("question_id", "issue_id", "affected_requirements", "question", "reason", "priority")}

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
