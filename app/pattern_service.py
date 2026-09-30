from __future__ import annotations

import json
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from .document_store import DocumentStore
from .pattern_models import (
    PatternCreateRequest,
    PatternModel,
    PatternSearchRequest,
    PatternSearchResult,
    PatternUpdateRequest,
)
from .repository import PersistenceError, SQLiteRepository

logger = logging.getLogger(__name__)


class PatternService:
    """Manages Pattern Knowledge Base business logic, SQLite persistence, and ChromaDB vector synchronization."""

    def __init__(self, repository: Optional[SQLiteRepository] = None, document_store: Optional[DocumentStore] = None):
        self.repository = repository or SQLiteRepository()
        self.document_store = document_store or DocumentStore()

    def seed_initial_patterns(self, seed_file_path: Optional[str] = None) -> List[PatternModel]:
        """Idempotently seed the initial canonical pattern knowledge base from seed_patterns.json."""
        if seed_file_path:
            path = Path(seed_file_path)
        else:
            path = Path(os.getenv("SEED_PATTERNS_PATH", "seed_patterns.json"))
            if not path.exists():
                path = Path(__file__).parent.parent / "seed_patterns.json"

        if not path.exists():
            logger.warning("seed_patterns.json file not found at %s; skipping pattern seeding", path)
            return []

        try:
            content = path.read_text(encoding="utf-8")
            data = json.loads(content)
            raw_patterns = data.get("patterns", [])
        except Exception as exc:
            logger.error("failed to read/parse seed_patterns.json: %s", exc)
            return []

        seeded: List[PatternModel] = []
        for raw in raw_patterns:
            pattern_id = raw.get("id") or ("PAT-" + uuid.uuid4().hex[:8].upper())
            name = raw.get("name")
            if not name or not raw.get("intent") or not raw.get("structure"):
                continue

            # Check if pattern already exists by name or ID
            existing = self.repository.get_pattern_by_name(name)
            if not existing:
                try:
                    existing = self.repository.get_pattern(pattern_id)
                except PersistenceError:
                    existing = None

            if not existing:
                saved = self.repository.save_pattern(
                    pattern_id=pattern_id,
                    name=name,
                    intent=raw["intent"],
                    structure=raw["structure"],
                    when_to_use=raw.get("when_to_use", []),
                    when_not_to_use=raw.get("when_not_to_use", []),
                    prerequisites=raw.get("prerequisites", []),
                    references=raw.get("references", []),
                    tags=raw.get("tags", []),
                    description=raw.get("description"),
                    strengths=raw.get("strengths"),
                    weaknesses=raw.get("weaknesses"),
                )
            else:
                saved = existing

            p_model = PatternModel.model_validate(saved)
            # Ensure Chroma vector index is synchronized
            self.document_store.add_pattern_vector(
                pattern_id=p_model.id,
                name=p_model.name,
                intent=p_model.intent,
                structure=p_model.structure,
                when_to_use=p_model.when_to_use,
                tags=p_model.tags,
                references=p_model.references,
            )
            seeded.append(p_model)

        logger.info("Pattern Knowledge Base startup seeding completed: %d patterns synchronized", len(seeded))
        return seeded

    def create_pattern(self, request: PatternCreateRequest) -> PatternModel:
        pattern_id = request.id or ("PAT-" + uuid.uuid4().hex[:8].upper())
        saved = self.repository.save_pattern(
            pattern_id=pattern_id,
            name=request.name.strip(),
            intent=request.intent.strip(),
            structure=request.structure,
            when_to_use=request.when_to_use,
            when_not_to_use=request.when_not_to_use,
            prerequisites=request.prerequisites,
            references=request.references,
            tags=request.tags,
            description=request.description,
            strengths=request.strengths,
            weaknesses=request.weaknesses,
        )
        p_model = PatternModel.model_validate(saved)
        self.document_store.add_pattern_vector(
            pattern_id=p_model.id,
            name=p_model.name,
            intent=p_model.intent,
            structure=p_model.structure,
            when_to_use=p_model.when_to_use,
            tags=p_model.tags,
            references=p_model.references,
        )
        return p_model

    def bulk_create_patterns(self, items: List[PatternCreateRequest]) -> List[PatternModel]:
        results: List[PatternModel] = []
        for item in items:
            results.append(self.create_pattern(item))
        return results

    def get_pattern(self, pattern_id: str) -> PatternModel:
        try:
            saved = self.repository.get_pattern(pattern_id)
            return PatternModel.model_validate(saved)
        except PersistenceError as exc:
            raise exc

    def list_patterns(self, tag: Optional[str] = None) -> List[PatternModel]:
        rows = self.repository.list_patterns(tag=tag)
        return [PatternModel.model_validate(r) for r in rows]

    def update_pattern(self, pattern_id: str, request: PatternUpdateRequest) -> PatternModel:
        kwargs = request.model_dump(exclude_unset=True)
        saved = self.repository.update_pattern(pattern_id, **kwargs)
        p_model = PatternModel.model_validate(saved)
        
        # Re-index vector in ChromaDB
        self.document_store.add_pattern_vector(
            pattern_id=p_model.id,
            name=p_model.name,
            intent=p_model.intent,
            structure=p_model.structure,
            when_to_use=p_model.when_to_use,
            tags=p_model.tags,
            references=p_model.references,
        )
        return p_model

    def delete_pattern(self, pattern_id: str) -> PatternModel:
        deleted_dict = self.repository.delete_pattern(pattern_id)
        self.document_store.delete_pattern_vector(pattern_id)
        return PatternModel.model_validate(deleted_dict)

    def search_patterns(self, request: PatternSearchRequest) -> List[PatternSearchResult]:
        hits = self.document_store.search_patterns(query=request.query, tags=request.tags, top_k=request.top_k)
        results: List[PatternSearchResult] = []

        for hit in hits:
            p_id = hit["pattern_id"]
            try:
                db_pattern = self.get_pattern(p_id)
            except PersistenceError:
                # Vector is stale (pattern deleted from DB)
                self.document_store.delete_pattern_vector(p_id)
                continue

            matched_fields = {
                "intent": db_pattern.intent,
                "structure": db_pattern.structure,
                "when_to_use": db_pattern.when_to_use,
            }

            results.append(
                PatternSearchResult(
                    pattern_id=db_pattern.id,
                    name=db_pattern.name,
                    score=hit["score"],
                    matched_fields=matched_fields,
                    pattern=db_pattern,
                )
            )

        return results
