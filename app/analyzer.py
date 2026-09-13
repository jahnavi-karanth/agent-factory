from __future__ import annotations

import hashlib
import json
import logging
import os
import re
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
        max_questions = int(os.getenv("MAX_CLARIFICATION_QUESTIONS", "20"))
        if not requirements.requirements:
            payload["quality_status"] = "INVALID"
            payload["status_reason"] = "The Requirements Model contains no meaningful requirements."
            payload["blocking_issues"] = []
        elif len(payload["clarification_questions"]) > max_questions:
            payload["quality_status"] = "NEEDS_REWORK"
            payload["status_reason"] = f"The analysis produced more than the configured maximum of {max_questions} clarification questions."
            payload["blocking_issues"] = [item.get("issue_id", "") for item in payload["issues"]]
        elif any(item.get("severity") == "CRITICAL" for item in payload["issues"]):
            payload["quality_status"] = "NEEDS_REWORK"
            payload["status_reason"] = "The analysis contains a critical unresolved issue that requires BRD rework before clarification."
            payload["blocking_issues"] = [item.get("issue_id", "") for item in payload["issues"] if item.get("severity") == "CRITICAL"]
        elif any(item.get("severity") in {"HIGH", "CRITICAL"} and item.get("clarification_required") for item in payload["issues"]):
            payload["quality_status"] = "READY_FOR_CLARIFICATION"
        else:
            payload["quality_status"] = "READY" if not payload["clarification_questions"] else "READY_FOR_CLARIFICATION"
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

    def generate_follow_up_questions(self, requirements: RequirementsModel, analysis: RequirementsAnalysis, answers: list[dict], round_number: int) -> list[dict]:
        if round_number > int(os.getenv("MAX_FOLLOW_UP_ROUNDS", "2")):
            return []
        schema = {
            "type": "object",
            "required": ["questions"],
            "properties": {"questions": {"type": "array", "items": {"type": "object", "required": ["question_id", "issue_id", "question", "reason", "priority"], "properties": {"question_id": {"type": "string"}, "issue_id": {"type": "string"}, "question": {"type": "string"}, "reason": {"type": "string"}, "priority": {"type": "string"}}}}},
        }
        prompt = f"""Review only the persisted Requirements Model, the original analysis, and the human answers below. Determine whether the answers reveal a genuinely new, material business ambiguity. If not, return an empty questions array. Do not create questions merely to use a round. Do not invent decisions, technical solutions, thresholds, actors, or policies. Questions must be neutral and reference an existing issue_id. This is bounded follow-up round {round_number}. Return at most 5 questions and use IDs Q-{round_number:01d}01, Q-{round_number:01d}02, etc.\n\nMODEL:\n{requirements.model_dump_json()}\nANALYSIS:\n{analysis.model_dump_json()}\nANSWERS:\n{json.dumps(answers)}"""
        quality_flags = self._answer_quality_flags(answers)
        if not quality_flags:
            return []
        raw = self.extractor.generate_json(prompt + f"\nANSWER QUALITY FLAGS:\n{json.dumps(quality_flags)}", schema)
        result = []
        issue_ids = {item.issue_id for item in analysis.issues}
        existing_ids = {item.question_id for item in analysis.clarification_questions}
        for index, item in enumerate(self._as_list(raw.get("questions") if isinstance(raw, dict) else []), start=1):
            if not isinstance(item, dict):
                continue
            issue_id = item.get("issue_id") or ""
            question = item.get("question") or ""
            if issue_id not in issue_ids or not question:
                continue
            question_id = item.get("question_id") or f"Q-{round_number:01d}{index:02d}"
            if question_id in existing_ids:
                question_id = f"Q-{round_number:01d}{index:02d}"
            affected = next((issue.affected_requirements for issue in analysis.issues if issue.issue_id == issue_id), [])
            result.append({"question_id": question_id, "issue_id": issue_id, "affected_requirements": affected, "question": question, "reason": item.get("reason") or "The human answer revealed a new ambiguity.", "priority": str(item.get("priority") or "MEDIUM").upper(), "round": round_number})
        if not result:
            question_lookup = {item.question_id: item for item in analysis.clarification_questions}
            for index, flag in enumerate(quality_flags, start=1):
                original = question_lookup.get(flag.get("question_id"))
                issue_id = original.issue_id if original else (flag.get("issue_id") or "")
                if not issue_id:
                    continue
                affected = original.affected_requirements if original else []
                priority = original.priority if original else "MEDIUM"
                question_text = original.question if original else flag.get("question", "the clarification question")
                result.append({"question_id": f"Q-{round_number:01d}{index:02d}", "issue_id": issue_id, "affected_requirements": affected, "question": f"Please provide a specific, direct answer to the original question: {question_text} If this is undecided, say whether you want the AI to recommend the best option.", "reason": flag["reason"], "priority": priority, "round": round_number})
        return result

    @staticmethod
    def _answer_quality_flags(answers: list[dict]) -> list[dict]:
        stop_words = {"the", "and", "for", "with", "what", "which", "should", "must", "are", "is", "be", "to", "of", "in", "on", "a", "an", "or", "users", "system"}
        undecided = re.compile(r"\b(undecided|not decided|not determined|unknown|unsure|tbd|to be decided|no decision|not specified|i don't know)\b", re.I)
        flags = []
        for item in answers:
            answer = str(item.get("answer", "")).strip()
            question = str(item.get("question", ""))
            answer_terms = {term[:4] for term in re.findall(r"[a-z]{4,}", answer.lower()) if term not in stop_words}
            question_terms = {term[:4] for term in re.findall(r"[a-z]{4,}", question.lower()) if term not in stop_words}
            overlap = len(answer_terms & question_terms) / max(1, min(len(question_terms), 5))
            reason = None
            if undecided.search(answer):
                reason = "The answer explicitly leaves the requested decision undecided."
            elif len(answer_terms) < 3:
                reason = "The answer is too short to resolve the requested business decision."
            elif question_terms and overlap == 0:
                reason = "The answer does not address the key terms in the clarification question."
            if reason:
                flags.append({"question_id": item.get("question_id"), "issue_id": item.get("issue_id"), "question": question, "reason": reason})
        return flags

    def generate_best_decisions(self, requirements: RequirementsModel, analysis: RequirementsAnalysis, answers: list[dict]) -> list[dict]:
        schema = {"type": "object", "required": ["decisions"], "properties": {"decisions": {"type": "array", "items": {"type": "object", "required": ["question_id", "decision", "reason"], "properties": {"question_id": {"type": "string"}, "decision": {"type": "string"}, "reason": {"type": "string"}}}}}}
        prompt = f"""For each flagged unanswered or irrelevant clarification answer, choose the most practical conservative business decision using only the supplied Requirements Model and question context. Do not invent unsupported facts. Prefer a minimal reversible option and clearly label it as an AI recommendation requiring review. Return one decision per flagged question.\nMODEL:\n{requirements.model_dump_json()}\nANALYSIS:\n{analysis.model_dump_json()}\nANSWERS:\n{json.dumps(answers)}"""
        raw = self.extractor.generate_json(prompt, schema)
        return [item for item in self._as_list(raw.get("decisions") if isinstance(raw, dict) else []) if isinstance(item, dict) and item.get("question_id") and item.get("decision")]

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
