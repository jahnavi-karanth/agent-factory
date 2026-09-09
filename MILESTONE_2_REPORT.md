# Milestone 2 — Requirements Analysis and Clarification Questions

## Implementation status

Implemented on branch `milestone-2-requirements-analysis`.

Milestone 2 consumes the validated Milestone 1 Requirements Model directly. It does not re-parse the BRD, create a database, accept human answers, modify requirements, or implement any later milestone.

## Architecture

```text
Milestone 1 Requirements Model
              |
              v
POST /api/requirements/analyze
              |
              v
RequirementsAnalyzer
              |
              v
Existing GeminiExtractor.generate_json()
              |
              v
Deterministic schema and reference validation
              |
              v
Issues + clarification questions
```

## API

```text
POST /api/requirements/analyze
Content-Type: application/json
```

The request body is the complete JSON Requirements Model returned by `POST /api/brd/upload`.

```bash
curl -X POST http://127.0.0.1:8000/api/requirements/analyze \
  -H 'Content-Type: application/json' \
  --data @requirements-model.json
```

The response includes:

- `brd_id`
- `analysis_id`
- `status`
- summary counts
- structured issues
- clarification questions
- affected requirement IDs

## Analysis behavior

The analysis prompt instructs Gemini to remain grounded in the Requirements Model, preserve existing requirement IDs, avoid inventing answers, identify only material issues, and ask neutral questions. Supported issue types are:

- `ambiguity`
- `gap`
- `conflict`
- `inconsistency`

Supported severities are `LOW`, `MEDIUM`, `HIGH`, and `CRITICAL`.

The deterministic validation layer verifies:

- Valid issue and question schemas.
- Unique issue IDs.
- Unique question IDs.
- Valid issue prefixes.
- Valid question prefixes.
- Existing affected requirement IDs.
- Questions reference existing issues.
- Summary counts match the returned findings.
- `status` matches whether findings/questions exist.

## Tests

Executed:

```text
18 passed, 1 warning
```

The suite includes Milestone 1 regression tests plus Milestone 2 tests for:

- Clear requirements with no findings.
- Ambiguous requirements.
- Missing information/gaps.
- Conflicting requirements.
- Neutral clarification questions.
- No hallucinated answers.
- Invalid requirement references.
- Malformed analysis output.
- Gemini/provider failure handling.
- API integration with a supplied Requirements Model.

## BRD 1 integration note

The user manually validated the live Milestone 1 BRD 1 upload and received a Requirements Model. That live JSON was not stored in this sandbox or included as an attachment, so I did not fabricate a live Gemini BRD 1 analysis result. The endpoint and analyzer are tested with a structurally valid Requirements Model, and the user can pass the actual BRD 1 response directly to the analysis endpoint.

## Files

- `app/analysis_models.py` — Milestone 2 issue, question, summary, and result schemas.
- `app/analyzer.py` — Generic analysis orchestration and grounded prompt.
- `app/llm.py` — Reused Gemini provider with its existing environment configuration, retries, timeout, and fallback behavior.
- `app/main.py` — Added `POST /api/requirements/analyze`.
- `tests/test_analysis.py` — Milestone 2 tests.
- `README.md` — API and severity documentation.

## Explicitly not implemented

- Human answer submission or resolution.
- Requirements mutation after answers.
- Pattern KB or RAG.
- Embeddings or pattern selection.
- Architecture generation.
- Code generation.
- Any Milestone 3 functionality.
