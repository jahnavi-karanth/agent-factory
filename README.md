# AI Software Development Factory

## Milestone 1: BRD Ingestion

This repository implements Milestones 1 and 2 plus persistence for their artifacts: accepting a user-supplied Business Requirements Document, producing a validated Requirements Model, analyzing it for material uncertainty, and persisting the resulting issues and clarification questions. It does **not** implement Pattern KB/RAG, architecture generation, code generation, or validation of generated software.

### Architecture

```text
User / Client
    |
    v
POST /api/brd/upload
    |
    v
File validation (extension, UTF-8, size, empty input)
    |
    v
Markdown/TXT document parser -> normalized document
    |
    v
RequirementExtractor interface -> GeminiExtractor
    |
    v
Pydantic RequirementsModel validation
    |
    v
SQLite repository: BRD + Requirements Model + Requirements
    |
    v
POST /api/requirements/analyze {"brd_id": "..."}
    |
    v
Milestone 2 analysis -> SQLite: Analysis + Issues + Questions
```

The repository BRDs are development fixtures only. Normal operation accepts uploaded content and does not read a BRD from the repository.

## Supported input

The supplied BRDs are Markdown files, so Milestone 1 supports `.md`, `.markdown`, and `.txt` UTF-8 documents. PDF/DOCX parsing is intentionally deferred until a provided BRD requires it. The default maximum upload size is 10 MiB and can be changed with `MAX_UPLOAD_BYTES`.

## Prerequisites and setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env` or in the process environment. The key is never stored in source code or logged. The default primary model is `gemini-3.5-flash-lite`. Optional variables are `GEMINI_MODEL`, `GEMINI_FALLBACK_MODEL` (default `gemini-3.5-flash`), `GEMINI_TIMEOUT_SECONDS` (default `180`), `GEMINI_MAX_RETRIES` (default `2`), `MAX_UPLOAD_BYTES`, `LOG_LEVEL`, and `DATABASE_PATH` (default `data/agent_factory.sqlite3`). A transient Gemini `503 UNAVAILABLE` response is retried with bounded exponential backoff and then attempted with the fallback model.

## Run the application

```bash
python -m uvicorn app.main:app --reload
```

Interactive OpenAPI documentation is available at <http://127.0.0.1:8000/docs>.

## Upload a BRD

```bash
curl -X POST http://127.0.0.1:8000/api/brd/upload \
  -F "file=@'Business Requirements Document — Corporate Expense Management Platform.md';type=text/markdown"
```

The request is multipart form data with one field named `file`. A successful response has this shape:

```json
{
  "brd_id": "BRD-<content-hash>",
  "title": "...",
  "source_filename": "requirements.md",
  "business_problem": "...",
  "business_objectives": [],
  "stakeholders": [],
  "user_roles": [],
  "requirements": [
    {
      "id": "REQ-001",
      "type": "functional",
      "description": "...",
      "source": {"section": "7.1", "title": "...", "line_start": null, "line_end": null},
      "priority": null
    }
  ],
  "non_functional_requirements": [],
  "business_rules": [],
  "constraints": [],
  "assumptions": [],
  "data_requirements": [],
  "external_dependencies": [],
  "success_criteria": [],
  "extraction_metadata": {"milestone": "1", "parser": "markdown", "provider": "gemini"}
}
```

If the file is invalid, empty, too large, unsupported, or Gemini cannot produce a valid model, the API returns a structured error with `error` and `detail` fields. No fallback requirements are fabricated.

## Tests

Tests mock the extraction provider, so they do not require a live Gemini key:

```bash
pytest -q
```

The suite covers health, upload, parsing, stable IDs, schema validation, source traceability, generic processing of another BRD, unsupported/empty files, and provider failure handling.

## Schema design

The model adds `source_filename`, `extraction_metadata`, and a structured `SourceReference` to the suggested schema. These preserve upload provenance and leave room for later traceability without changing the core requirement shape. Missing BRD categories remain empty lists or `null`; priorities are never inferred.

## SQLite persistence

The application uses SQLite through `app/repository.py`; route handlers and Gemini code do not contain SQL. The default database file is:

```text
data/agent_factory.sqlite3
```

Set `DATABASE_PATH` to choose another location. The database contains `brds`, `requirements_models`, `requirements`, `analyses`, `issues`, `issue_requirements`, `clarification_questions`, and `question_requirements`. Foreign keys and indexes preserve BRD → Requirements Model → Requirement → Analysis → Issue/Question traceability. Every upload creates a persisted Requirements Model version, and every analysis creates a separate analysis record; prior analyses are not silently overwritten.

### Persisted workflow

1. `POST /api/brd/upload` validates and extracts the BRD, persists its metadata, Requirements Model, and individual requirements, then returns the model.
2. `POST /api/requirements/analyze` accepts `{"brd_id": "BRD-..."}`, retrieves the latest persisted Requirements Model, analyzes it, atomically persists the analysis, issues, questions, and relationships, then returns the result.
3. The previous full Requirements Model request format remains supported for compatibility, but the recommended workflow uses only `brd_id`.

### Retrieval APIs

```text
GET /api/brd/{brd_id}/requirements
GET /api/analysis/{analysis_id}
```

The first returns the persisted Requirements Model with stable requirement IDs and source references. The second returns the persisted analysis, summary, issues, questions, and affected requirement relationships. Data survives application restarts.

### Reset the development database

Stop the application, then remove the local SQLite file:

```bash
rm -f data/agent_factory.sqlite3
```

The database is recreated automatically at the next application start. Do not remove a database containing artifacts you need to retain.

## Known limitations and assumptions

- Gemini is the only production extractor currently implemented, behind the `RequirementExtractor` interface.
- Only UTF-8 Markdown/plain text is supported because those are the formats present in the supplied fixtures.
- SQLite is intended for the current development/demo environment; the repository abstraction allows a later datastore replacement.
- Requirement ordering and IDs are validated as sequential `REQ-001`, `REQ-002`, etc. The extractor is instructed to emit them in document order.
- Milestone 2 identifies ambiguity, gaps, conflicts, and inconsistencies but does not accept human answers or resolve requirements.

## Milestone 2: Requirements Analysis and Clarification Questions

Milestone 2 consumes the validated Milestone 1 Requirements Model from SQLite by `brd_id`. It does not re-parse the original BRD. It asks Gemini to identify only meaningful ambiguity, gaps, conflicts, and inconsistencies, then validates all issue and question references deterministically.

### Analyze a Requirements Model

```text
POST /api/requirements/analyze
Content-Type: application/json
```

The recommended request body contains only the BRD ID persisted by Milestone 1:

```bash
curl -X POST http://127.0.0.1:8000/api/requirements/analyze \
  -H 'Content-Type: application/json' \
  -d '{"brd_id":"BRD-..."}'
```

The response contains `analysis_id`, `status`, a summary, structured issues, and neutral clarification questions. Existing requirement IDs are preserved and every referenced ID must exist in the submitted model.

Issue severity uses this vocabulary:

| Severity | Meaning |
|---|---|
| `LOW` | Minor uncertainty unlikely to affect architecture |
| `MEDIUM` | Could affect implementation or one component |
| `HIGH` | Could materially affect workflow, data, security, integrations, or architecture |
| `CRITICAL` | Could fundamentally change the design or make implementation incorrect |

Milestone 2 does not accept human answers or modify requirements. Human answer resolution belongs to a later milestone.

## Milestone 3: Human-in-the-Loop clarification

Milestone 3 is limited to business clarification and resolution. It does not implement RAG, Pattern KB retrieval, architecture generation, code generation, or testing agents.

### Database migrations

The project uses Alembic for reproducible SQLite schema creation. On a fresh clone:

```bash
python -m pip install -r requirements.txt
alembic upgrade head
```

The default database is `data/agent_factory.sqlite3`. Set `DATABASE_PATH` to use another SQLite file. The migration is safe for an existing database created by the earlier persistence layer: it preserves existing rows and adds the new versioning, audit, and HITL tables.

The application still initializes missing tables defensively for compatibility with older development databases; Alembic is the authoritative schema setup for clean environments.

### BRD quality statuses

M2 exposes `quality_status` in addition to its analysis status:

| Status | Meaning | HITL allowed? |
|---|---|---:|
| `INVALID` | The input is not meaningfully usable as a BRD. | No |
| `NEEDS_REWORK` | The BRD is recognizable but too incomplete or contradictory to proceed safely. | No |
| `READY_FOR_CLARIFICATION` | The BRD is usable and has bounded answerable questions. | Yes |
| `READY` | No meaningful clarification is required. | No |

The backend applies the status from validated analysis results and the configured question limit. It does not invent business decisions.

### Clarification safeguards

Configure these in `.env`:

```env
MAX_CLARIFICATION_QUESTIONS=20
MAX_FOLLOW_UP_ROUNDS=2
```

The question limit is a safety ceiling, not a target. The current implementation persists follow-up-round state and does not automatically rerun the full M2 analysis after each answer.

### HITL API and WebSocket

Create a session from a persisted M2 analysis:

```text
POST /api/hitl/session
{"analysis_id":"ANALYSIS-..."}
```

A session is created only when the analysis is `READY_FOR_CLARIFICATION` and contains questions. Sessions are rejected for `INVALID`, `NEEDS_REWORK`, `READY`, or analyses with no questions.

Retrieve a resumable session:

```text
GET /api/hitl/session/{session_id}
```

Connect to:

```text
/ws/hitl/{session_id}
```

The server sends structured messages such as:

```json
{"type":"question","question":{"question_id":"Q-001","question":"..."}}
```

Answer with:

```json
{"type":"answer","question_id":"Q-001","answer":"Managers approve expenses."}
```

The server acknowledges the answer, persists it, advances to the next unanswered question, and sends `completed` after all questions are answered. Disconnecting and reconnecting resumes from the first unanswered question. Completed clarification creates a new resolved Requirements Model version while preserving the original model.

### Audit trail

Meaningful business events are persisted in `audit_logs`, including BRD upload, Requirements Model creation, analysis start/completion, HITL session creation, question presentation, answer receipt/recording, completion, failures, and resolved-model creation. Secrets and API keys are never placed in audit metadata.

## Current limitations

- The initial status classifier is deterministic around validated M2 findings and configured limits; richer semantic BRD quality classification can be expanded later without changing the persistence or HITL interfaces.
- Follow-up question generation is intentionally bounded and not automatically fabricated. Human answers are persisted as the source of truth and are attached to the resolved model metadata; the original Requirements Model is never overwritten.
