# Milestone 3 End-to-End Test Guide

## Scope

This guide validates Alembic migrations, BRD versioning, quality statuses, audit events, initial HITL questions, follow-up rounds, WebSocket reconnection, resolved Requirements Models, and negative cases. Swagger handles REST calls. The browser console handles the WebSocket because Swagger UI does not provide a live WebSocket client.

## Setup

```bash
cd /Users/jahnavikaranth/Desktop/agent-factory
git checkout milestone-3-hitl
git pull origin milestone-3-hitl
source .venv/bin/activate
python -m pip install -r requirements.txt
```

For an isolated test database, set this in `.env`:

```env
DATABASE_PATH=data/milestone3-test.sqlite3
MAX_CLARIFICATION_QUESTIONS=20
MAX_FOLLOW_UP_ROUNDS=2
```

Initialize a fresh database:

```bash
rm -f data/milestone3-test.sqlite3
alembic upgrade head
python -m uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000/docs`.

## Case 1: Migration and schema

Run `alembic upgrade head` on an empty database. It must finish successfully. Verify tables:

```bash
sqlite3 data/milestone3-test.sqlite3 ".tables"
```

Expected tables include `brds`, `brd_versions`, `requirements_models`, `requirements`, `analyses`, `issues`, `clarification_questions`, `hitl_sessions`, `hitl_answers`, `hitl_follow_up_questions`, `resolved_requirements_models`, and `audit_logs`.

Run `alembic upgrade head` a second time. It must be idempotent.

## Case 2: Upload and version history

Use `POST /api/brd/upload` and upload a Markdown BRD. Copy `brd_id`. Verify `GET /api/brd/{brd_id}/requirements` returns HTTP 200. Verify `GET /api/brd/{brd_id}/versions` returns version 1.

Upload the same filename again with revised content. The stable filename-based BRD identity should remain the same and the versions endpoint should show version 1 and version 2. Historical Requirements Models must remain in SQLite.

## Case 3: M2 status outcomes

Use `POST /api/requirements/analyze` with:

```json
{"brd_id":"BRD-..."}
```

A normal analysis with questions should return `quality_status: READY_FOR_CLARIFICATION`. A clear analysis with no questions should return `READY`. An analysis with a critical issue should return `NEEDS_REWORK`. A model with no requirements should return `INVALID`. Every non-ready result must include `status_reason`.

Verify the selected status through `GET /api/brd/{brd_id}/versions`; the latest version must contain the same `quality_status`.

## Case 4: Audit trail

Call `GET /api/audit?entity_id=BRD-...` and `GET /api/audit?entity_id=ANALYSIS-...`. Verify upload, model creation, analysis start, and analysis completion events. Do not find `GEMINI_API_KEY` or any secret in `details_json`.

## Case 5: Create a HITL session

Use an analysis with `READY_FOR_CLARIFICATION` and at least one question. Call `POST /api/hitl/session`:

```json
{"analysis_id":"ANALYSIS-..."}
```

Copy `session_id`. Call `GET /api/hitl/session/{session_id}` and verify `ACTIVE`, `follow_up_round: 0`, and the initial questions.

Attempt to create a session for `READY`, `INVALID`, `NEEDS_REWORK`, or an analysis with no questions. Each must return HTTP 409 and create no session.

## Case 6: Initial WebSocket answers

In the browser console, replace the session ID:

```javascript
const sessionId = "HITL-...";
const ws = new WebSocket(`ws://127.0.0.1:8000/ws/hitl/${sessionId}`);
ws.onmessage = (event) => {
  const message = JSON.parse(event.data);
  console.log(message);
  if (message.type === "question") {
    const answer = prompt(`${message.question.question_id}\n\n${message.question.question}`);
    if (answer && answer.trim()) {
      ws.send(JSON.stringify({type:"answer", question_id:message.question.question_id, answer:answer.trim()}));
    }
  }
};
```

Expected sequence: `resumed`, `question`, `answer_acknowledged`, then another question or `completed`. Verify the session through Swagger and verify every answer is present.

## Case 7: Reconnection

Create a new session from the same analysis. Connect and answer only Q-001. When Q-002 is presented, run `ws.close()` without answering it. Use `GET /api/hitl/session/{session_id}` and verify the session is `ACTIVE`, Q-001 is in `answers`, and Q-002 is unanswered.

Reconnect with the same session ID:

```javascript
const wsResume = new WebSocket("ws://127.0.0.1:8000/ws/hitl/HITL-...");
wsResume.onmessage = event => console.log(JSON.parse(event.data));
```

The first question after `resumed` must be Q-002, not Q-001. Answer the remaining questions and verify completion.

## Case 8: Follow-up round

Use an analysis whose initial question is answered with information that reveals a new ambiguity. The follow-up provider evaluates the persisted model, original analysis, and answers. When a follow-up is generated, the WebSocket sends `answer_acknowledged`, then a new `question`. Its session state must show `follow_up_round: 1`.

Answer the follow-up question. If no new ambiguity remains, the WebSocket sends `completed`. Verify `GET /api/hitl/session/{session_id}` includes both initial and follow-up answers, and `GET /api/audit?entity_id=HITL-...` includes `FOLLOW_UP_ROUND_STARTED` and `FOLLOW_UP_QUESTION_CREATED`.

Repeat with a fixture/provider that generates new ambiguity twice. The second follow-up round may proceed when `MAX_FOLLOW_UP_ROUNDS=2`. A further generated round must return an error, audit `HITL_SESSION_FAILED` with a rework reason, and never create an endless loop.

Answer-quality policy: an answer that is clearly irrelevant to the question, explicitly says `undecided`, `unknown`, `TBD`, or similar, or is too short to express a decision receives a targeted follow-up asking for a specific answer. A slightly vague but relevant answer may pass without another question. When the configured maximum is reached while the current answer is still unresolved, the analyzer returns an AI best-decision recommendation, persists it in `best_decisions`, emits a `best_decisions` WebSocket message, and completes rather than looping. Review the recommendation before treating it as an approved business decision.

## Case 9: Resolved model and traceability

After all initial and follow-up questions are answered, call `GET /api/brd/{brd_id}/requirements`. The latest version must have `extraction_metadata.resolved: true` and the session ID. The original Requirements Model must remain available in the version history. Query SQLite to verify one row in `resolved_requirements_models` links the resolved model version to the source model version.

## Case 10: Invalid inputs and failures

Test an empty file, unsupported extension, invalid UTF-8, oversized file, missing BRD ID, missing analysis ID, missing session ID, empty WebSocket answer, wrong question ID, and malformed WebSocket message. Verify structured errors, no state advancement, and no HITL session for invalid/rework cases.

## Case 11: Restart survival

With an active session after answering one question, stop Uvicorn and start it again. Retrieve the session through Swagger and reconnect to the same WebSocket URL. The next unanswered question must resume. After completion, restart again and retrieve the BRD, analysis, session, audit events, and version history.

## Case 12: SQLite verification

```bash
sqlite3 data/milestone3-test.sqlite3 "SELECT session_id,status,follow_up_round,current_question_id FROM hitl_sessions;"
sqlite3 data/milestone3-test.sqlite3 "SELECT session_id,question_id,answer FROM hitl_answers;"
sqlite3 data/milestone3-test.sqlite3 "SELECT action,entity_type,entity_id,result FROM audit_logs ORDER BY id;"
sqlite3 data/milestone3-test.sqlite3 "SELECT brd_id,version,quality_status,status_reason FROM brd_versions ORDER BY brd_id,version;"
```

## Expected final acceptance flow

```text
alembic upgrade head
→ upload BRD
→ M1 Requirements Model persisted
→ M2 analysis persisted
→ READY_FOR_CLARIFICATION
→ create HITL session
→ answer initial questions
→ optionally generate bounded follow-up round(s)
→ reconnect without repeating answered questions
→ persist all answers
→ create resolved Requirements Model
→ preserve original model and version history
→ verify audit trail
→ restart application
→ retrieve all artifacts successfully
```
