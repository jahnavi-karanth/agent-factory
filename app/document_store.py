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
        item_metadata = {
            "document_id": document_id,
            "section_id": "SEC-001",
            "section_title": filename,
            "page": 1,
            "kind": "text",
            "project_id": project_id,
            "filename": filename,
            **(metadata or {}),
        }
        collection.upsert(ids=[document_id], documents=[text], embeddings=[self._embedding(text)], metadatas=[item_metadata])

    def add_chunks(self, document_id: str, project_id: str, chunks: list[Dict[str, Any]]) -> None:
        if not chunks:
            return
        collection = self._get_collection()
        ids = []
        documents = []
        embeddings = []
        metadatas = []
        for index, chk in enumerate(chunks):
            chunk_id = chk.get("chunk_id") or f"{document_id}_chk_{index+1}"
            text = chk.get("text") or ""
            metadata = {
                "document_id": document_id,
                "section_id": str(chk.get("section_id", "SEC-001")),
                "section_title": str(chk.get("section_title", "Overview")),
                "page": int(chk.get("page") or 1),
                "kind": str(chk.get("kind", "text")),
                "project_id": str(project_id),
            }
            ids.append(chunk_id)
            documents.append(text)
            embeddings.append(self._embedding(text))
            metadatas.append(metadata)
        collection.upsert(ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas)

    def search(self, project_id: str, query: str, limit: int = 5) -> list[Dict[str, Any]]:
        result = self._get_collection().query(query_embeddings=[self._embedding(query)], n_results=limit, where={"project_id": project_id})
        return [{"id": item_id, "document": document, "metadata": metadata} for item_id, document, metadata in zip(result.get("ids", [[]])[0], result.get("documents", [[]])[0], result.get("metadatas", [[]])[0])]

