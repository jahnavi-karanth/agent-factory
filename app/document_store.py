from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Optional


class DocumentStore:
    """Small project-scoped Chroma adapter; embeddings are deterministic and local."""

    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("CHROMA_PATH", str(Path("data") / "chroma"))
        self._collection = None

    def _get_collection(self):
        if self._collection is None:
            import chromadb
            client = chromadb.PersistentClient(path=self.path)
            self._collection = client.get_or_create_collection("documents", metadata={"hnsw:space": "cosine"})
        return self._collection

    @staticmethod
    def _embedding(text: str, dimensions: int = 64) -> list[float]:
        values = [0.0] * dimensions
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:2], "big") % dimensions
            values[index] += 1.0 if digest[2] % 2 else -1.0
        norm = sum(value * value for value in values) ** 0.5 or 1.0
        return [value / norm for value in values]

    def add(self, document_id: str, project_id: str, filename: str, text: str, metadata: Optional[Dict[str, Any]] = None) -> None:
        collection = self._get_collection()
        item_metadata = {"project_id": project_id, "filename": filename, **(metadata or {})}
        collection.upsert(ids=[document_id], documents=[text], embeddings=[self._embedding(text)], metadatas=[item_metadata])

    def search(self, project_id: str, query: str, limit: int = 5) -> list[Dict[str, Any]]:
        result = self._get_collection().query(query_embeddings=[self._embedding(query)], n_results=limit, where={"project_id": project_id})
        return [{"id": item_id, "document": document, "metadata": metadata} for item_id, document, metadata in zip(result.get("ids", [[]])[0], result.get("documents", [[]])[0], result.get("metadatas", [[]])[0])]
