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

    def _get_patterns_collection(self):
        import chromadb
        client = chromadb.PersistentClient(path=self.path)
        return client.get_or_create_collection("patterns", metadata={"hnsw:space": "cosine"})

    @staticmethod
    def construct_pattern_embedding_text(intent: str, structure: Any, when_to_use: list[str]) -> str:
        struct_text = "\n".join(f"- {s}" for s in structure) if isinstance(structure, list) else str(structure)
        wtu_text = "\n".join(f"- {w}" for w in when_to_use) if isinstance(when_to_use, list) else str(when_to_use)
        return f"Intent:\n{intent}\n\nStructure:\n{struct_text}\n\nWhen to use:\n{wtu_text}".strip()

    def add_pattern_vector(
        self,
        pattern_id: str,
        name: str,
        intent: str,
        structure: Any,
        when_to_use: list[str],
        tags: list[str],
        references: list[str],
    ) -> None:
        collection = self._get_patterns_collection()
        embedding_text = self.construct_pattern_embedding_text(intent, structure, when_to_use)
        metadata = {
            "pattern_id": pattern_id,
            "name": name,
            "tags": ",".join(tags or []),
            "source": references[0] if references else "canonical",
        }
        collection.upsert(ids=[pattern_id], documents=[embedding_text], embeddings=[self._embedding(embedding_text)], metadatas=[metadata])

    def delete_pattern_vector(self, pattern_id: str) -> None:
        try:
            collection = self._get_patterns_collection()
            collection.delete(ids=[pattern_id])
        except Exception:
            pass

    def search_patterns(self, query: str, tags: Optional[list[str]] = None, top_k: int = 8) -> list[Dict[str, Any]]:
        collection = self._get_patterns_collection()
        count = collection.count()
        if count == 0:
            return []

        limit = min(max(1, top_k), min(count, 50))
        result = collection.query(
            query_embeddings=[self._embedding(query)],
            n_results=limit,
            include=["documents", "metadatas", "distances"],
        )

        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        hits = []
        clean_tags = [t.lower().strip() for t in (tags or []) if t.strip()]

        for item_id, doc, meta, dist in zip(ids, docs, metadatas, distances):
            item_tags = [t.lower().strip() for t in meta.get("tags", "").split(",") if t.strip()]
            if clean_tags and not any(ct in item_tags for ct in clean_tags):
                continue
            similarity_score = round(1.0 / (1.0 + max(0.0, float(dist))), 4)
            hits.append({
                "pattern_id": item_id,
                "name": meta.get("name", item_id),
                "distance": float(dist),
                "score": similarity_score,
                "metadata": meta,
                "document": doc,
            })

        hits.sort(key=lambda x: x["score"], reverse=True)
        return hits[:limit]


