# AI Software Development Factory

## Milestone 1: BRD Ingestion

This repository implements only the first factory milestone: accepting a user-supplied Business Requirements Document and producing a validated, structured Requirements Model. It does **not** implement ambiguity analysis, clarification, Pattern KB/RAG, architecture generation, code generation, or validation of generated software.

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
JSON response with stable REQ-### IDs and source references
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

Set `GEMINI_API_KEY` in `.env` or in the process environment. The key is never stored in source code or logged. The default is the stable `gemini-3.5-flash`, which supports structured outputs and is designed for higher-speed, lower-cost multi-step workflows. Optional variables are `GEMINI_MODEL`, `GEMINI_TIMEOUT_SECONDS` (default `180`), `GEMINI_MAX_RETRIES` (default `1`), `MAX_UPLOAD_BYTES`, and `LOG_LEVEL`. For interactive BRD ingestion, use a supported Flash model; a slower model may require increasing `GEMINI_TIMEOUT_SECONDS`.

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

## Known limitations and assumptions

- Gemini is the only production extractor currently implemented, behind the `RequirementExtractor` interface.
- Only UTF-8 Markdown/plain text is supported because those are the formats present in the supplied fixtures.
- The API does not persist workflow state or results; persistence belongs to a later milestone.
- Requirement ordering and IDs are validated as sequential `REQ-001`, `REQ-002`, etc. The extractor is instructed to emit them in document order.
- This milestone extracts stated content only. It deliberately does not detect ambiguity, gaps, contradictions, or clarification questions.
