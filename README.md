# AI Software Development Factory

## Overview

This repository implements the **AI Software Development Factory** backend:
- **Milestone 1**: Project management, authentication, FileStore file storage, multi-format document ingestion (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`), parsing, section/chunk extraction, SQLite persistence, ChromaDB vector store embeddings with mandatory `project_id` metadata and isolation, and document status/sections APIs.
- **Milestone 2**: Requirements Analysis, quality status classification (`INVALID`, `NEEDS_REWORK`, `READY_FOR_CLARIFICATION`, `READY`), gap/ambiguity issue identification, and neutral clarification questions.
- **Milestone 3**: Human-in-the-Loop (HITL) WebSocket clarification sessions, follow-up round generation, best-decision fallbacks, workflow runs, and event streams.
- **Pattern Knowledge Base**: Global architectural & agentic pattern registry (source-of-truth in SQLite `patterns` table, semantic search index in ChromaDB `patterns` collection), startup idempotent seeding from `seed_patterns.json` (includes all 10 canonical patterns: ReAct, Reflection, Planner-Executor, Multi-Agent Debate, Router, RAG, Tool-Use, Hierarchical Agents, Critic-Refine, Map-Reduce), REST CRUD APIs, and tag-filtered semantic vector search.

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

### 3. Changes Made for Pattern Knowledge Base
- **Pydantic Models** ([`app/pattern_models.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/pattern_models.py)):
  - Defined `PatternModel`, `PatternCreateRequest`, `PatternUpdateRequest`, `PatternSearchRequest`, `PatternSearchResult`.
- **Database Schema & Migration** ([`app/repository.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/repository.py), [`alembic/versions/0005_patterns_table.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/alembic/versions/0005_patterns_table.py)):
  - Created relational `patterns` table in SQLite (`id`, `name`, `intent`, `structure`, `when_to_use`, `when_not_to_use`, `prerequisites`, `references`, `tags`, `description`, `strengths`, `weaknesses`, `created_at`, `updated_at`).
  - Implemented repository methods: `save_pattern`, `get_pattern`, `get_pattern_by_name`, `list_patterns`, `update_pattern`, `delete_pattern`.
- **Semantic Vector Indexing** ([`app/document_store.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/document_store.py)):
  - Created ChromaDB `patterns` collection.
  - Implemented deterministic embedding text construction (`intent + structure + when_to_use`), `add_pattern_vector`, `delete_pattern_vector`, and `search_patterns`.
- **Pattern Service & Startup Seeding** ([`app/pattern_service.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/pattern_service.py)):
  - Implemented idempotent startup pattern seeding from `seed_patterns.json` at root.
  - Managed complete DB and Chroma synchronization on pattern creation, updates, deletions, and searches.
- **REST Endpoints & Route Wiring** ([`app/main.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/app/main.py)):
  - Registered `POST /patterns`, `POST /patterns/bulk`, `POST /patterns/search`, `GET /patterns`, `GET /patterns/{pattern_id}`, `PATCH /patterns/{pattern_id}`, `DELETE /patterns/{pattern_id}`.
- **Test Suite** ([`tests/test_patterns.py`](file:///Users/jahnavikaranth/Desktop/agent-factory/tests/test_patterns.py)):
  - Added 6 test functions verifying startup seeding, CRUD operations, bulk creation, semantic vector search, tag filtering, and stale vector cleanup.

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
    ├── GET /projects/{project_id}/documents/search?q=... -> Project-filtered vector search (where={"project_id": project_id})
    │
    └── Pattern Knowledge Base (Global Resource):
          ├── Startup Seeding -> Reads seed_patterns.json -> Synchronizes SQLite & ChromaDB
          ├── POST /patterns & POST /patterns/bulk -> Create pattern(s)
          ├── GET /patterns & GET /patterns/{id} -> List / fetch patterns from SQLite (source of truth)
          ├── PATCH /patterns/{id} & DELETE /patterns/{id} -> Update / delete pattern & sync ChromaDB
          └── POST /patterns/search -> Semantic search via ChromaDB (intent + structure + when_to_use)
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

### 2. Pattern Knowledge Base APIs

```bash
# List all patterns
curl -X GET http://127.0.0.1:8000/patterns

# List patterns by tag
curl -X GET http://127.0.0.1:8000/patterns?tag=reasoning

# Get pattern details by ID
curl -X GET http://127.0.0.1:8000/patterns/PAT-001

# Semantic search for patterns
curl -X POST http://127.0.0.1:8000/patterns/search \
  -H "Content-Type: application/json" \
  -d '{"query":"iterative reasoning with external tools","top_k":3}'

# Create custom pattern
curl -X POST http://127.0.0.1:8000/patterns \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Custom Agent Pattern",
    "intent": "Solve multi-step tasks using specialized sub-agents",
    "structure": ["Decompose", "Delegate", "Synthesize"],
    "when_to_use": ["Complex modular workflows"],
    "tags": ["multi-agent", "custom"]
  }'
```

---

## Test Execution

Run the complete test suite (90 tests):

```bash
uv run pytest
```

All tests mock external services and run locally using temporary SQLite databases and Chroma stores.
