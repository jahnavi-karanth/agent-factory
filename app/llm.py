from __future__ import annotations

import json
import os
import socket
import time
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
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None, timeout: Optional[float] = None, max_retries: Optional[int] = None, fallback_model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        self.fallback_model = fallback_model if fallback_model is not None else os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")
        self.timeout = timeout if timeout is not None else float(os.getenv("GEMINI_TIMEOUT_SECONDS", "180"))
        self.max_retries = max_retries if max_retries is not None else int(os.getenv("GEMINI_MAX_RETRIES", "2"))

    def extract(self, document: NormalizedDocument) -> Dict[str, Any]:
        if not self.api_key:
            raise ExtractionError("GEMINI_API_KEY is not configured")
        prompt = self._build_prompt(document)
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": EXTRACTION_SCHEMA},
        }
        body = json.dumps(payload).encode("utf-8")
        last_error: Optional[Exception] = None
        models = [self.model]
        if self.fallback_model and self.fallback_model not in models:
            models.append(self.fallback_model)
        for model_index, model in enumerate(models):
            endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            for attempt in range(self.max_retries + 1):
                if attempt:
                    time.sleep(min(2 ** (attempt - 1), 8))
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
                    if exc.code != 503:
                        raise ExtractionError(f"Gemini extraction failed: {last_error}") from last_error
                    # A 503 is usually transient; retries continue, then the fallback model is tried.
                except (error.URLError, socket.timeout, TimeoutError, KeyError, IndexError, json.JSONDecodeError, ValueError) as exc:
                    last_error = exc
                    if model_index == len(models) - 1 and attempt == self.max_retries:
                        break
        raise ExtractionError(f"Gemini extraction failed after bounded retries: {last_error}") from last_error

    @staticmethod
    def _build_prompt(document: NormalizedDocument) -> str:
        headings = "\n".join(f"- line {line}: {title}" for level, title, line in document.headings)
        return f"""Extract only information explicitly present in the submitted business requirements document. Do not infer, invent, or fill gaps with domain knowledge. Return JSON matching the requested schema. Assign requirements sequential IDs REQ-001, REQ-002, ... in document order. For each requirement source, use only a heading title and line number from the supplied heading catalog; if the source cannot be identified reliably, use null rather than a filename or invented section. Use null or [] when a category is absent. Do not analyze ambiguity, conflicts, or missing information; this is ingestion only.\n\nDocument filename: {document.filename}\n\nHEADING CATALOG:\n{headings or '(no headings detected)'}\n\nDOCUMENT:\n{document.text}"""
