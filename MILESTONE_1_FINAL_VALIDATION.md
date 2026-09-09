# Milestone 1 Final Quality Validation

**Branch:** `milestone-1-brd-ingestion`  
**Validation commit:** `33320f8`  
**Scope:** Milestone 1 — BRD ingestion only

## Executive result

**Milestone 1 is ready for approval, with one audit limitation:** the exact JSON response produced by the user’s manual Gemini run was not included in the repository or attachments, so the literal text of every generated requirement cannot be independently compared line-by-line. The implementation was audited against BRD 1, the extraction contract, the reported Gemini outputs, and automated tests. The reported failures were corrected.

No Milestone 2 functionality was implemented.

## A. PASS/FAIL checklist

| Check | Result | Evidence or finding |
|---|---|---|
| BRD 1 is accepted through the upload endpoint | PASS | Existing endpoint and integration test use the uploaded fixture, not an internal file read. |
| BRD parsing is separated from extraction | PASS | `app/parser.py` produces a normalized document before extraction. |
| Requirements Model is schema-validated before response | PASS | `RequirementsModel.model_validate()` runs in `IngestionService`; FastAPI also validates the response model. |
| Requirement IDs are unique and consistently generated | PASS | The model requires sequential `REQ-001`, `REQ-002`, … IDs and rejects duplicates or gaps. |
| Explicit assumptions are represented separately | PASS | BRD 1 contains four explicit assumptions under section 12; the application does not create assumptions in deterministic code. |
| Constraints are correctly represented | PASS | BRD 1 has no section titled Constraints and no explicit constraints section; `constraints: []` is correct unless Gemini extracts an explicitly stated constraint elsewhere. |
| Business rules are represented separately | PASS | BRD 1 has six explicit rules under section 8. |
| Priorities are not invented | PASS | The requirement priority field is nullable; extraction instructions require `null` when priority is absent. |
| External systems/integrations are not invented | PASS | No external integration is hardcoded; absent BRD information remains empty. |
| Source traceability is grounded | PASS after fix | Gemini receives the actual heading catalog. Returned source titles are retained only when matched to real headings; fabricated filename/section values are cleared. |
| `original_type` is part of the canonical model | PASS — removed | It was a provider normalization artifact, not needed for later traceability. It is no longer in `Requirement`; any incoming copy is removed before validation. |
| Invalid files are handled | PASS | Unsupported extensions, invalid UTF-8, empty files, and oversized uploads return structured errors. |
| Gemini/API failures are handled | PASS | Missing keys, malformed responses, timeouts, HTTP failures, and 503 overloads use bounded failure/retry behavior. |
| Secrets are protected | PASS | Keys are read from `GEMINI_API_KEY`; no real key is in source or `.env.example`. |
| Implementation is generic | PASS | Domain-specific BRD terminology appears only in test fixtures and documentation examples, not in `app/`. |
| Automated tests exist and run | PASS | 11 tests passed in the final audit run. |
| Later milestones were not implemented | PASS | No ambiguity, gap, conflict, clarification, RAG, pattern selection, architecture, or code-generation workflow exists. |

## B. Issues found during audit

### 1. Source references could be fabricated by model output

The previous extraction prompt did not provide Gemini with the document’s heading catalog. The user reported source objects containing a filename-like title and no useful section. This was a traceability weakness.

**Resolution:** the prompt now includes the actual heading catalog with source line numbers. The service accepts only titles matched to real headings and derives numeric section prefixes only from matched headings. Unmatched titles and invented section numbers become `null`; they are not fabricated.

For BRD 1, valid headings include section 7.1 `User Access`, section 7.2 `Expense Creation`, section 8 `Business Rules`, section 9 `Non-Functional Requirements`, section 12 `Assumptions`, and section 13 `Success Criteria`.

### 2. `original_type` was unnecessary in the canonical model

It was introduced to preserve unknown Gemini labels such as `user_experience`. It is not needed for the current traceability chain and would make the canonical schema provider-specific.

**Resolution:** unknown labels are normalized to `other`, and `original_type` has been removed from the canonical `Requirement` model. Incoming copies are discarded before validation.

### 3. Gemini output category variation

Gemini returned labels such as `Functional` and `user_experience`. The first caused strict validation failure; the second was outside the canonical vocabulary.

**Resolution:** deterministic normalization maps known aliases to canonical categories and maps unknown categories to `other`. This is normalization, not requirement invention.

## C. Fixes made

The final audit commit contains:

- Heading-catalog grounding in the Gemini extraction prompt.
- Source title and section verification against actual uploaded-document headings.
- Clearing of fabricated source titles and section numbers.
- Removal of `original_type` from the canonical Requirements Model.
- Removal of incoming provider-only `original_type` values.
- Expanded requirement-type normalization.
- Regression tests for title-cased categories, unknown categories, and fabricated source headings.

## D. Final Requirements Model contract for BRD 1

The exact live Gemini JSON response was not captured in the project, so the literal generated descriptions cannot be reproduced or certified from this audit alone. The validated model contract and grounded BRD 1 category expectations are:

```json
{
  "brd_id": "BRD-<content-hash>",
  "title": "Corporate Expense Management Platform",
  "source_filename": "Business Requirements Document — Corporate Expense Management Platform.md",
  "business_problem": "Only statements from section 1, Executive Summary.",
  "business_objectives": "Only the objectives explicitly listed in section 2.",
  "stakeholders": [
    "Employees",
    "Managers",
    "Finance Team",
    "Finance Leadership",
    "System Administrators"
  ],
  "user_roles": "Only roles explicitly stated in the BRD.",
  "requirements": [
    {
      "id": "REQ-001",
      "type": "functional | non_functional | business_rule | constraint | data | other",
      "description": "An explicit statement from the BRD.",
      "source": {
        "section": "A section number derived only from a matched BRD heading, or null",
        "title": "A title matched only to an actual BRD heading, or null",
        "line_start": "A reliable source line, or null",
        "line_end": null
      },
      "priority": null
    }
  ],
  "non_functional_requirements": "Explicit statements from section 9 and other clearly labeled non-functional content.",
  "business_rules": [
    "The six explicit rules under section 8, if extracted as a category."
  ],
  "constraints": [],
  "assumptions": [
    "The platform will initially be used internally by the organization.",
    "Employees and managers will have authenticated access to the system.",
    "Company expense policies will continue to be maintained by the finance organization.",
    "The platform will assist with expense processing but will not replace financial policies or finance responsibilities."
  ],
  "data_requirements": [
    "Users, departments, reporting relationships, expenses, expense categories, receipts/supporting documents, approval decisions, comments, notifications, and expense history."
  ],
  "external_dependencies": [],
  "success_criteria": "The explicit criteria listed under section 13.",
  "extraction_metadata": {
    "milestone": "1",
    "parser": "markdown",
    "provider": "gemini"
  }
}
```

The four assumptions above are the only statements classified as explicit assumptions by the BRD’s own section 12. Inferred assumptions must not be placed there.

`constraints: []` is correct for the current BRD because it contains no explicit Constraints section or clearly labeled constraint statements. Scope limitations are not automatically converted into constraints.

## E. Tests executed

Command:

```bash
pytest -q
```

Final result:

```text
11 passed, 1 warning
```

Additional checks passed:

```bash
python3 -m compileall -q app tests
git diff --check
```

The test suite covers upload, parsing, BRD 1 fixture processing, genericity, unsupported and empty files, extractor failure, duplicate IDs, title-cased category normalization, unknown-category normalization, and source-heading validation.

## F. Remaining limitations

1. The exact live BRD 1 Gemini response was not saved, so a literal claim that every generated sentence is grounded cannot be made without exporting that JSON for review.
2. Source line ranges are only retained when Gemini supplies a valid line start; the service does not invent line numbers.
3. The application uses a single synchronous Gemini extraction request with bounded retries and fallback; it does not persist workflow state.
4. Markdown and UTF-8 text are supported; PDF/DOCX parsing remains out of scope until required by a provided BRD.
5. The application does not yet perform ambiguity, gap, conflict, clarification, pattern, RAG, architecture, or code-generation work.

## Final decision

**PASS — Milestone 1 is ready for approval.** The remaining limitation is evidence availability for the exact live model output, not an identified implementation defect. Milestone 2 should begin only after approval.
