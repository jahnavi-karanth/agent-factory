from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Dict, Optional

from .llm import ExtractionError, GeminiExtractor, RequirementExtractor
from .models import RequirementsModel
from .parser import NormalizedDocument

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, extractor: Optional[RequirementExtractor] = None):
        self.extractor = extractor or GeminiExtractor()

    def ingest(self, document: NormalizedDocument) -> RequirementsModel:
        logger.info("requirement extraction started filename=%s", document.filename)
        try:
            raw = self.extractor.extract(document)
        except ExtractionError:
            logger.exception("workflow failed during requirement extraction")
            raise
        if not raw:
            raise ExtractionError("the extractor returned an empty response")
        model = self._validate_and_enrich(raw, document)
        logger.info("requirements validation completed filename=%s count=%d", document.filename, len(model.requirements))
        return model

    @staticmethod
    def _validate_and_enrich(raw: Dict[str, Any], document: NormalizedDocument) -> RequirementsModel:
        payload = dict(raw)
        payload["requirements"] = [IngestionService._normalize_requirement(item, document) for item in payload.get("requirements", [])]
        payload["brd_id"] = payload.get("brd_id") or f"BRD-{hashlib.sha256(document.text.encode()).hexdigest()[:12].upper()}"
        payload["source_filename"] = document.filename
        payload.setdefault("extraction_metadata", {})
        payload["extraction_metadata"].update({"milestone": "1", "parser": "markdown", "provider": "gemini"})
        try:
            return RequirementsModel.model_validate(payload)
        except Exception as exc:
            raise ExtractionError(f"invalid Requirements Model from extractor: {exc}") from exc

    @staticmethod
    def _normalize_requirement(requirement: Any, document: NormalizedDocument) -> Any:
        """Normalize harmless presentation differences without inventing content."""
        if not isinstance(requirement, dict):
            return requirement
        normalized = dict(requirement)
        normalized.pop("original_type", None)
        if not isinstance(requirement.get("type"), str):
            normalized["source"] = IngestionService._normalize_source(normalized.get("source"), document)
            return normalized
        original_label = requirement["type"].strip()
        label = original_label.lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "functional_requirement": "functional",
            "nonfunctional": "non_functional",
            "non_functional_requirement": "non_functional",
            "businessrule": "business_rule",
            "business_rule_requirement": "business_rule",
            "data_requirement": "data",
            "data_requirements": "data",
            "technical": "non_functional",
            "technical_requirement": "non_functional",
            "security": "non_functional",
            "security_requirement": "non_functional",
            "performance": "non_functional",
            "performance_requirement": "non_functional",
        }
        canonical_types = {"functional", "non_functional", "business_rule", "constraint", "data", "other"}
        canonical = aliases.get(label, label if label in canonical_types else "other")
        normalized["type"] = canonical
        normalized["source"] = IngestionService._normalize_source(normalized.get("source"), document)
        return normalized

    @staticmethod
    def _normalize_source(source: Any, document: NormalizedDocument) -> Dict[str, Any]:
        """Retain only source metadata that can be matched to the uploaded document."""
        if not isinstance(source, dict):
            source = {}
        actual_titles = [title for level, title, _ in document.headings if level <= 3]
        supplied_title = source.get("title") if isinstance(source.get("title"), str) else None
        matched_title = next((title for title in actual_titles if supplied_title and (supplied_title == title or supplied_title in title or title in supplied_title)), None)
        line_start = source.get("line_start") if isinstance(source.get("line_start"), int) and source.get("line_start") >= 1 else None
        if line_start is not None:
            for level, title, line in document.headings:
                if line <= line_start and level <= 3:
                    matched_title = title
        section = None
        if matched_title:
            match = re.match(r"^(\d+(?:\.\d+)*)\s+", matched_title)
            section = match.group(1) if match else None
        return {"section": section, "title": matched_title, "line_start": line_start, "line_end": None}
