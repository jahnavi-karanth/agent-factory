# Milestone 1 Completion Report — BRD Ingestion

## Status

**Complete.** This project contains only Milestone 1. Milestone 2 and later milestones have not been implemented.

## Implemented workflow

```text
User / Client
    ↓
POST /api/brd/upload
    ↓
File validation
    ↓
Markdown/TXT parser
    ↓
Normalized BRD content
    ↓
Gemini requirement extraction
    ↓
Pydantic Requirements Model validation
    ↓
Structured JSON response
```

## Main capabilities

- Accepts an uploaded `.md`, `.markdown`, or `.txt` BRD through `POST /api/brd/upload`.
- Validates file type, UTF-8 encoding, empty input, and maximum size.
- Parses the uploaded document without depending on repository BRD fixtures.
- Uses a provider-neutral `RequirementExtractor` interface with a Gemini implementation.
- Reads `GEMINI_API_KEY` from the environment; no credentials are hardcoded.
- Validates model output, including required fields, sequential unique `REQ-###` IDs, and source references.
- Returns structured errors for invalid input, provider failures, and malformed model output.
- Includes automated tests using a mocked extractor.

## Run locally

```bash
cd agent-factory
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Set GEMINI_API_KEY in .env or export it in the shell.
python -m uvicorn app.main:app --reload
```

Gemini settings can be adjusted in `.env`: `GEMINI_MODEL` (default `gemini-3.5-flash`), `GEMINI_FALLBACK_MODEL` (default `gemini-3.5-flash-lite`), `GEMINI_TIMEOUT_SECONDS` (default `180`), and `GEMINI_MAX_RETRIES` (default `2`). A transient Gemini `503 UNAVAILABLE` response is retried with bounded exponential backoff, then attempted with the fallback model. `gemini-3.5-flash` is a stable model with structured-output support. Use a supported Flash model for interactive ingestion.

OpenAPI documentation is available at `http://127.0.0.1:8000/docs`.

## Upload a BRD

```bash
curl -X POST http://127.0.0.1:8000/api/brd/upload \
  -F "file=@Business Requirements Document — Corporate Expense Management Platform.md"
```

## Run tests

```bash
pytest -q
```

Verified result: **8 tests passed**. The tests mock Gemini so a live API key is not required for the test suite.

## BRD 1 verification

The supplied Corporate Expense Management BRD was submitted through the same upload endpoint used by normal clients during the integration test. Parsing, extraction orchestration, source handling, and Requirements Model validation were exercised.

A live Gemini call was not made in the current environment because `GEMINI_API_KEY` is not configured. The real endpoint correctly returns a structured `502` error rather than fabricating requirements when the key is absent.

## Files of interest

| File | Purpose |
|---|---|
| `app/main.py` | FastAPI app and upload endpoint |
| `app/parser.py` | Generic document parsing and normalization |
| `app/llm.py` | Gemini adapter and extractor interface |
| `app/models.py` | Requirements Model and validation |
| `app/service.py` | Ingestion orchestration |
| `tests/test_ingestion.py` | Milestone 1 automated tests |
| `.env.example` | Configuration template |
| `README.md` | Full setup and API documentation |
| `seed_patterns.json` | Future Pattern KB fixture; not used in Milestone 1 |

## Intentionally deferred

- Ambiguity, gap, and conflict analysis
- Impact classification
- Human clarification workflow
- Pattern KB ingestion and RAG
- Pattern evaluation and selection
- Architecture generation
- Code generation
- Workflow persistence
