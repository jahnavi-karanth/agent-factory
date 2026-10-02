# AI Software Development Factory

## Overview

This repository implements the **AI Software Development Factory** backend:
- **Milestone 1**: Project management, authentication, FileStore file storage, multi-format document ingestion (`.pdf`, `.docx`, `.pptx`, `.xlsx`, `.md`, `.txt`), parsing, section/chunk extraction, SQLite persistence, ChromaDB vector store embeddings with mandatory `project_id` metadata and isolation, and document status/sections APIs.
- **Milestone 2**: Requirements Analysis, quality status classification (`INVALID`, `NEEDS_REWORK`, `READY_FOR_CLARIFICATION`, `READY`), gap/ambiguity issue identification, and neutral clarification questions.
- **Milestone 3**: Human-in-the-Loop (HITL) WebSocket clarification sessions, follow-up round generation, best-decision fallbacks, workflow runs, and event streams.
- **Milestone 4 (Combined Project and Code Planning Workflow)**:
  - **Document-to-Requirements Bridge**: Launch planning workflows from ingested documents (`document_ids`) or existing requirements models (`requirements_model_version_id`).
  - **LangGraph `PlanningWorkflow` Orchestration**:
    1. Complexity Classification (`simple` vs `complex` routing based on requirement and NFR metrics).
    2. Pattern Selection (Retrieves architectural design patterns from the Pattern Knowledge Base).
    3. Multi-Source Parallel Research (Queries document chunks, pattern KB, web search, and LLM synthesis with strict citation tags `[doc:...]`, `[kb:...]`, `[web:...]`, `[llm]`).
    4. Architecture Specification (`Architecture.md` and `Architecture.json` generated for complex routes).
    5. Task Planning (Generates atomic implementation tasks with strict sequencing, file targets, dependencies, requirement mappings, and acceptance criteria).
    6. Quality Validation (Enforces requirement coverage, topological sequence ordering, pattern fidelity, atomicity, and citations).
    7. Human-in-the-Loop Approval Gate (WebSocket & REST approval prompts with interrupt support).
    8. Artifact Finalization (Persists `Architecture.json`, `Architecture.md`, and `Tasks.json` to project run directories).
  - **Task Editing & Splitting**: REST endpoints (`PATCH /projects/{project_id}/runs/{run_id}/tasks/{task_id}`) supporting description edits, sequence reordering, and task splits into subtasks prior to plan approval.
- **Pattern Knowledge Base**: Global architectural & agentic pattern registry (source-of-truth in SQLite `patterns` table, semantic search index in ChromaDB `patterns` collection), startup idempotent seeding from `seed_patterns.json` (includes 10 canonical patterns: ReAct, Reflection, Planner-Executor, Multi-Agent Debate, Router, RAG, Tool-Use, Hierarchical Agents, Critic-Refine, Map-Reduce), REST CRUD APIs, and tag-filtered semantic vector search.

---

## Architecture Overview

```text
Client / Frontend
    │
    ├── Authentication & Projects (JWT Token)
    │     ├── POST /auth/register & POST /auth/login -> JWT Token
    │     └── POST /projects -> Create Project Aggregate (status: draft|ready|running|archived)
    │
    ├── Document Processing Pipeline
    │     ├── POST /projects/{project_id}/documents (Multipart upload: .pdf, .docx, .pptx, .xlsx, .md, .txt)
    │     ├── FileStore -> ./data/projects/{project_id}/uploads/{document_id}.{ext}
    │     ├── Parser -> Text & Headings Extraction -> Sections & Chunks (SEC-001, CHK-001)
    │     ├── SQLite Repository -> Persist documents, document_sections, document_chunks
    │     └── DocumentStore (ChromaDB) -> Upsert chunks to `documents` collection
    │
    ├── Workflow 1 — Requirements Workflow (M1-M3)
    │     ├── POST /projects/{project_id}/workflows/requirements
    │     ├── LangGraph Workflow -> Analysis -> Gap Identification -> Question Generation
    │     ├── WS /projects/{project_id}/runs/{run_id}/hitl -> Real-time Q&A Popups
    │     └── POST /projects/{project_id}/runs/{run_id}/approve & /reject
    │
    ├── Workflow 2 — Combined Project & Code Planning Workflow (M4)
    │     ├── POST /projects/{project_id}/workflows/planning (Document-to-Requirements Bridge)
    │     ├── LangGraph PlanningWorkflow -> Complexity Route -> Pattern KB Selection -> Multi-Source Research
    │     ├── Architecture Specification -> Architecture.md & Architecture.json
    │     ├── Task Planning & Quality Validation -> Topological Sequence, Atomicity, Citations
    │     ├── Task Patching & Splitting -> PATCH /projects/{project_id}/runs/{run_id}/tasks/{task_id}
    │     ├── Approval Gate -> WS & REST (/projects/{project_id}/runs/{run_id}/approve & /reject)
    │     └── Artifact Generation -> Architecture.json, Architecture.md, Tasks.json
    │
    └── Pattern Knowledge Base (Global Resource):
          ├── Startup Seeding -> Reads seed_patterns.json -> Synchronizes SQLite & ChromaDB
          ├── POST /patterns & POST /patterns/bulk -> Create pattern(s)
          ├── GET /patterns & GET /patterns/{id} -> List / fetch patterns from SQLite (source of truth)
          ├── PATCH /patterns/{id} & DELETE /patterns/{id} -> Update / delete pattern & sync ChromaDB
          └── POST /patterns/search -> Semantic search via ChromaDB (intent + structure + when_to_use)
```

---

## Milestone 4 REST Endpoints

| Method | Route | Description |
|---|---|---|
| `POST` | `/projects/{project_id}/workflows/planning` | Start Planning Workflow via document bridge or requirements model (`202 Accepted`) |
| `GET` | `/projects/{project_id}/runs/{run_id}/tasks` | Retrieve implementation tasks for a planning run |
| `PATCH` | `/projects/{project_id}/runs/{run_id}/tasks/{task_id}` | Edit task description, target files, sequence, or split task into subtasks |
| `POST` | `/projects/{project_id}/runs/{run_id}/approve` | Approve plan via REST fallback (unlocks code generation stage) |
| `POST` | `/projects/{project_id}/runs/{run_id}/reject` | Reject plan with feedback via REST fallback (triggers revision loop) |
| `GET` | `/projects/{project_id}/runs/{run_id}/patterns` | Retrieve selected design patterns |
| `GET` | `/projects/{project_id}/runs/{run_id}/research` | Retrieve multi-source research findings & citation tags |
| `GET` | `/projects/{project_id}/runs/{run_id}/architecture` | Retrieve generated architecture specification (JSON & Markdown) |
| `GET` | `/projects/{project_id}/runs/{run_id}/artifacts` | Consolidated endpoint for patterns, research, architecture, and tasks |
| `GET` | `/projects/{project_id}/runs/{run_id}/events` | Real-time Server-Sent Events (SSE) stream for run status updates |
| `WS` | `/projects/{project_id}/runs/{run_id}/hitl` | Dual-workflow WebSocket endpoint for interactive prompts & approval popups |

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

Run Alembic schema migrations (up to `0006_planning_tables`):

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

## End-to-End Planning Workflow Usage Guide

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

### 2. Upload Document and Launch Planning Workflow

```bash
# Upload document
curl -X POST http://127.0.0.1:8000/projects/PROJ-001/documents \
  -H "Authorization: Bearer <token>" \
  -F "file=@expense_brd.md"

# Start Planning Workflow via Document Bridge
curl -X POST http://127.0.0.1:8000/projects/PROJ-001/workflows/planning \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"document_ids":["DOC-001"]}'
```

### 3. Fetch Tasks and Edit/Split

```bash
# Get Tasks
curl -X GET http://127.0.0.1:8000/projects/PROJ-001/runs/RUN-001/tasks \
  -H "Authorization: Bearer <token>"

# Split Task TASK-002 into Subtasks
curl -X PATCH http://127.0.0.1:8000/projects/PROJ-001/runs/RUN-001/tasks/TASK-002 \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "split_into": [
      {
        "title": "Subtask 2.1 — Service Layer",
        "description": "Implement service methods.",
        "target_files": ["app/service.py"],
        "acceptance_criteria": ["Methods run without errors"]
      },
      {
        "title": "Subtask 2.2 — Repository Layer",
        "description": "Implement repository queries.",
        "target_files": ["app/repository.py"],
        "acceptance_criteria": ["Queries pass unit tests"]
      }
    ]
  }'
```

### 4. Approve Plan

```bash
curl -X POST http://127.0.0.1:8000/projects/PROJ-001/runs/RUN-001/approve \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{}'
```

---

## Test Execution

Run the complete test suite (111 unit & integration tests):

```bash
./.venv/bin/pytest -q
```

All tests mock external LLM/web services and run locally using temporary SQLite databases and Chroma stores.
