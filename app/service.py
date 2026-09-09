from __future__ import annotations

import hashlib
import logging
from typing import Any

from .llm import ExtractionError, GeminiExtractor, RequirementExtractor
from .models import RequirementsModel
from .parser import NormalizedDocument

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, extractor: RequirementExtractor | None = None):
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
    def _validate_and_enrich(raw: dict[str, Any], document: NormalizedDocument) -> RequirementsModel:
        payload = dict(raw)
        payload["brd_id"] = payload.get("brd_id") or f"BRD-{hashlib.sha256(document.text.encode()).hexdigest()[:12].upper()}"
        payload["source_filename"] = document.filename
        payload.setdefault("extraction_metadata", {})
        payload["extraction_metadata"].update({"milestone": "1", "parser": "markdown", "provider": "gemini"})
        try:
            return RequirementsModel.model_validate(payload)
        except Exception as exc:
            raise ExtractionError(f"invalid Requirements Model from extractor: {exc}") from exc
