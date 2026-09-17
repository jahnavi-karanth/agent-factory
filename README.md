# AI Software Development Factory

## Overview

This repository implements the **AI Software Development Factory** backend:
- **Milestone 1**: Project management, authentication, FileStore file storage, multi-format document ingestion (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`), parsing, section/chunk extraction, SQLite persistence, ChromaDB vector store embeddings with mandatory `project_id` metadata and isolation, and document status/sections APIs.
- **Milestone 2**: Requirements Analysis, quality status classification (`INVALID`, `NEEDS_REWORK`, `READY_FOR_CLARIFICATION`, `READY`), gap/ambiguity issue identification, and neutral clarification questions.
- **Milestone 3**: Human-in-the-Loop (HITL) WebSocket clarification sessions, follow-up round generation, best-decision fallbacks, workflow runs, and event streams.

---

## Change History & Reference Log

### 1. Changes Made Prior to M1 Completion Prompt
- **OpenAPI Authorize Button Fix**: Updated `app/auth.py` to use FastAPI's `HTTPBearer(auto_error=False)` security scheme instead of a plain header parameter. This populates `components.securitySchemes` in `openapi.json` and renders the green **Authorize** padlock button at the top right of Swagger UI (`/docs`).
- **Environment Variable Loading (.env)**: Added `load_dotenv()` in `app/main.py` and `app/llm.py` so that `os.getenv("GEMINI_API_KEY")` and other parameters automatically load from `.env` on server startup.
- **`python-dotenv` Dependency**: Added `python-dotenv>=1.0,<2` to `requirements.txt`.

### 2. Changes Made for Official Milestone 1 Completion
- **FileStore Abstraction** ([`app/filestore.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/filestore.py)):
  - Implemented `FileStore` class storing uploaded raw files at `./data/projects/{project_id}/uploads/{document_id}.{ext}`.
  - Built-in path traversal defenses against malicious filenames (`../../evil.txt`, absolute paths, special characters).
- **Database Schema Extensions** ([`app/repository.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/repository.py)):
  - Updated `projects` table to include `status` (`draft`, `ready`, `running`, `archived`) and `updated_at`.
  - Added tables `documents`, `document_sections`, and `document_chunks` for persistence.
  - Added repository CRUD methods: `list_projects`, `update_project`, `save_document`, `get_document`, `save_document_sections_and_chunks`, `list_document_sections`, and `list_document_chunks`.
- **Alembic Migration** ([`alembic/versions/0004_documents_and_project_status.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/alembic/versions/0004_documents_and_project_status.py)):
  - Created migration `0004_documents_and_project_status` for reproducible schema setup.
- **Document Parser & Chunking** ([`app/parser.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/parser.py)):
  - Extended text extraction for all 6 supported file formats (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`).
  - Implemented `extract_sections_and_chunks()` returning `ParsedSection` and `ParsedChunk` with stable section IDs (`SEC-001`, `SEC-002`...) and chunk IDs.
- **Vector Store Embeddings & Project Isolation** ([`app/document_store.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/document_store.py)):
  - Added `add_chunks()` method storing chunk-level entries in ChromaDB's `documents` collection with mandatory metadata: `document_id`, `section_id`, `section_title`, `page`, `kind`, `project_id`.
  - Enforced `where={"project_id": project_id}` filter on all vector search operations.
- **REST API Endpoints** ([`app/main.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/main.py)):
  - `POST /auth/login` (alias for `POST /auth/token`)
  - `POST /projects` (creates project, validates status in `draft`, `ready`, `running`, `archived`)
  - `GET /projects` (lists all projects owned by authenticated user)
  - `GET /projects/{project_id}` (retrieves single project; 404 if unauthorized/missing)
  - `PATCH /projects/{project_id}` (updates project name and/or status; 404 if unauthorized/missing)
  - `POST /projects/{project_id}/documents` (multipart file upload for all 6 formats, FileStore storage, parsing, DB persistence, and ChromaDB chunk vector embedding)
  - `GET /projects/{project_id}/documents/{document_id}` (retrieves document parse status & section/chunk counts)
  - `GET /projects/{project_id}/documents/{document_id}/sections` (retrieves structured document sections)
- **Official Milestone 1 Tests** ([`tests/test_m1_official.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/tests/test_m1_official.py)):
  - Added 9 comprehensive integration test functions covering authentication, project lifecycle & isolation, all 6 file formats, path traversal defense, document status, section structure, and ChromaDB project isolation search.
  - All 84 tests in the test suite pass with zero regressions across M1, M2, and M3.

---

## Architecture Overview

```text
Client / Frontend
    │
    ├── POST /auth/register & POST /auth/login -> JWT Token
    │
    ├── POST /projects -> Create Project Aggregate (status: draft|ready|running|archived)
    │
    ├── POST /projects/{project_id}/documents (Multipart upload: .pdf, .docx, .pptx, .xlsx, .md, .txt)
    │     ├── FileStore -> ./data/projects/{project_id}/uploads/{document_id}.{ext}
    │     ├── Parser -> Text & Headings Extraction -> Sections & Chunks (SEC-001, CHK-001)
    │     ├── SQLite Repository -> Persist documents, document_sections, document_chunks
    │     └── DocumentStore (ChromaDB) -> Upsert chunks to `documents` collection
    │           └── Mandatory Metadata: document_id, section_id, section_title, page, kind, project_id
    │
    ├── GET /projects/{project_id}/documents/{document_id} -> Status & counts
    ├── GET /projects/{project_id}/documents/{document_id}/sections -> Section outline
    └── GET /projects/{project_id}/documents/search?q=... -> Project-filtered vector search (where={"project_id": project_id})
```

---

## Supported Input Formats

- **Markdown**: `.md`, `.markdown`
- **Plain Text**: `.txt`
- **PDF**: `.pdf`
- **Word Document**: `.docx`
- **PowerPoint Presentation**: `.pptx`
- **Excel Spreadsheet**: `.xlsx`

Maximum upload size defaults to 10 MiB (configurable via `MAX_UPLOAD_BYTES`).

---

## Setup & Quickstart

### 1. Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### 2. Database Migrations

Run Alembic schema migrations:

```bash
alembic upgrade head
```

### 3. Running the Server

Start the Uvicorn development server:

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open interactive Swagger UI docs at: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## End-to-End API Usage Guide

### 1. Register and Login

```bash
# Register User
curl -X POST http://127.0.0.1:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"Password123!"}'

# Login to get JWT Token
curl -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"dev@example.com","password":"Password123!"}'
```

Response:
```json
{
  "access_token": "<jwt-token-string>",
  "token_type": "bearer"
}
```

### 2. Create and Manage Projects

```bash
TOKEN="<jwt-token-string>"

# Create Project
curl -X POST http://127.0.0.1:8000/projects \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"Expense Management Platform","status":"draft"}'

# List Projects
curl -X GET http://127.0.0.1:8000/projects \
  -H "Authorization: Bearer $TOKEN"

# Update Project Status to 'ready'
curl -X PATCH http://127.0.0.1:8000/projects/PROJ-123456 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"status":"ready"}'
```

### 3. Upload Project Document

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJ-123456/documents \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@'Business Requirements Document — Corporate Expense Management Platform.md';type=text/markdown"
```

Response:
```json
{
  "document_id": "DOC-A1B2C3D4E5F6",
  "project_id": "PROJ-123456",
  "filename": "Business Requirements Document — Corporate Expense Management Platform.md",
  "file_type": ".md",
  "storage_path": "/.../data/projects/PROJ-123456/uploads/DOC-A1B2C3D4E5F6.md",
  "status": "COMPLETED",
  "error_message": null,
  "section_count": 8,
  "chunk_count": 24,
  "created_at": "2026-09-15T12:00:00+00:00",
  "updated_at": "2026-09-15T12:00:00+00:00"
}
```

### 4. Check Document Status & Retrieve Sections

```bash
# Get Document Status
curl -X GET http://127.0.0.1:8000/projects/PROJ-123456/documents/DOC-A1B2C3D4E5F6 \
  -H "Authorization: Bearer $TOKEN"

# Get Document Sections Outline
curl -X GET http://127.0.0.1:8000/projects/PROJ-123456/documents/DOC-A1B2C3D4E5F6/sections \
  -H "Authorization: Bearer $TOKEN"
```

### 5. Project-Scoped Document Search

```bash
curl -X GET "http://127.0.0.1:8000/projects/PROJ-123456/documents/search?q=receipts" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Test Execution

Run the complete test suite (84 tests):

```bash
uv run pytest
```

All tests mock external services and run locally using temporary SQLite databases and Chroma stores.
