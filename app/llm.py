from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Protocol
from urllib import error, request

from .parser import NormalizedDocument


class ExtractionError(RuntimeError):
    """Raised when a valid requirements model cannot be produced."""


class RequirementExtractor(Protocol):
    def extract(self, document: NormalizedDocument) -> Dict[str, Any]: ...


EXTRACTION_SCHEMA = {
    "type": "object",
    "required": [
        "title", "business_problem", "business_objectives", "stakeholders", "user_roles",
        "requirements", "non_functional_requirements", "business_rules", "constraints",
        "assumptions", "data_requirements", "external_dependencies", "success_criteria",
    ],
    "properties": {
        "title": {"type": "string"},
        "business_problem": {"type": "string"},
        "business_objectives": {"type": "array", "items": {"type": "string"}},
        "stakeholders": {"type": "array", "items": {"type": "string"}},
        "user_roles": {"type": "array", "items": {"type": "string"}},
        "requirements": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "type", "description", "source", "priority"],
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "description": {"type": "string"},
                    "source": {
                        "type": "object",
                        "properties": {
                            "section": {"type": "string"},
                            "title": {"type": "string"},
                            "line_start": {"type": "integer"},
                            "line_end": {"type": "integer"},
                        },
                    },
                    "priority": {"type": "string"},
                },
            },
        },
        "non_functional_requirements": {"type": "array", "items": {"type": "string"}},
        "business_rules": {"type": "array", "items": {"type": "string"}},
        "constraints": {"type": "array", "items": {"type": "string"}},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "data_requirements": {"type": "array", "items": {"type": "string"}},
        "external_dependencies": {"type": "array", "items": {"type": "string"}},
        "success_criteria": {"type": "array", "items": {"type": "string"}},
    },
}


class GeminiExtractor:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: float = 60.0, max_retries: int = 1):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self.timeout = timeout
        self.max_retries = max_retries

    def extract(self, document: NormalizedDocument) -> Dict[str, Any]:
        if not self.api_key:
            raise ExtractionError("GEMINI_API_KEY is not configured")
        prompt = self._build_prompt(document)
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": EXTRACTION_SCHEMA},
        }
        body = json.dumps(payload).encode("utf-8")
        last_error: Optional[Exception] = None
        for _ in range(self.max_retries + 1):
            try:
                req = request.Request(endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST")
                with request.urlopen(req, timeout=self.timeout) as response:
                    raw = json.loads(response.read().decode("utf-8"))
                text = raw["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                if not isinstance(parsed, dict):
                    raise ValueError("Gemini returned a non-object JSON value")
                return parsed
            except error.HTTPError as exc:
                error_body = exc.read().decode("utf-8", errors="replace")[:500]
                last_error = RuntimeError(f"Gemini HTTP {exc.code}: {error_body}")
            except (error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
        raise ExtractionError(f"Gemini extraction failed after bounded retries: {last_error}") from last_error

    @staticmethod
    def _build_prompt(document: NormalizedDocument) -> str:
        return f"""Extract only information explicitly present in the submitted business requirements document. Do not infer, invent, or fill gaps with domain knowledge. Return JSON matching the requested schema. Assign requirements sequential IDs REQ-001, REQ-002, ... in document order. Preserve precise Markdown heading and line references when available. Use null or [] when a category is absent. Do not analyze ambiguity, conflicts, or missing information; this is ingestion only.\n\nDocument filename: {document.filename}\n\nDOCUMENT:\n{document.text}"""
