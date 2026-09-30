from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


class FileStore:
    """Project-scoped file storage abstraction with path traversal protection."""

    def __init__(self, data_root: Optional[str] = None):
        self.data_root = Path(data_root or os.getenv("DATA_ROOT", "data")).resolve()

    def _get_upload_dir(self, project_id: str) -> Path:
        # Sanitize project_id to prevent path traversal
        clean_project_id = Path(project_id).name
        upload_dir = (self.data_root / "projects" / clean_project_id / "uploads").resolve()
        # Verify upload_dir is inside data_root
        if not str(upload_dir).startswith(str(self.data_root)):
            raise ValueError("Invalid project path; path traversal attempt detected")
        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir

    def save_file(self, project_id: str, document_id: str, filename: str, content: bytes) -> str:
        upload_dir = self._get_upload_dir(project_id)
        # Extract extension safely
        clean_filename = Path(filename).name
        ext = Path(clean_filename).suffix.lower() or ".bin"
        clean_doc_id = Path(document_id).name
        
        file_path = (upload_dir / f"{clean_doc_id}{ext}").resolve()
        if not str(file_path).startswith(str(upload_dir)):
            raise ValueError("Invalid document filename; path traversal attempt detected")
            
        file_path.write_bytes(content)
        return str(file_path)

    def get_file_content(self, project_id: str, document_id: str, ext: str) -> bytes:
        upload_dir = self._get_upload_dir(project_id)
        clean_doc_id = Path(document_id).name
        clean_ext = ext if ext.startswith(".") else f".{ext}"
        file_path = (upload_dir / f"{clean_doc_id}{clean_ext}").resolve()
        
        if not str(file_path).startswith(str(upload_dir)):
            raise ValueError("Invalid document path; path traversal attempt detected")
            
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
            
        return file_path.read_bytes()
