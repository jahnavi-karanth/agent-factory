# Milestone 4 — Combined Project and Code Planning Workflow Test Guide

This document provides complete instructions for testing and verifying **Milestone 4: Combined Project and Code Planning** in the `agent-factory` system via Swagger UI, curl, WebSockets, and SSE.

---

## 1. Overview of Milestone 4 Capabilities

Milestone 4 introduces the second primary workflow engine to the AI Software Development Factory:
- **Document-to-Requirements Bridge**: Launch planning directly from ingested project documents (`document_ids`) or existing requirements models (`requirements_model_version_id`).
- **LangGraph `PlanningWorkflow` Orchestration**:
  1. `load_approved_requirements`
  2. `classify_complexity` (Routes to `simple` or `complex` path based on requirement metrics)
  3. `select_patterns` (Queries Pattern Knowledge Base for matching architecture patterns)
  4. `parallel_research` (Executes parallel multi-source research across `doc`, `kb`, `web`, and `llm`)
  5. `architecture_design` (Generates structured JSON & Markdown `Architecture.md`/`Architecture.json` for `complex` route)
  6. `task_planning` (Generates atomic implementation tasks with strict sequencing, dependencies, target files, and AC)
  7. `validate_plan` (Automated checks for requirement coverage, topological ordering, pattern fidelity, atomicity, and citations)
  8. `approval_gate` (WebSocket / REST Human-in-the-Loop approval gate with interrupt)
  9. `finalize` (Writes `Architecture.json`, `Architecture.md`, and `Tasks.json` to persistent storage)
- **Task Patching & Editing**: Reorder sequence numbers, modify target files/descriptions, and split tasks into subtasks prior to plan approval.

---

## 2. API Endpoints Reference (Milestone 4)

| HTTP Method | Endpoint Path | Description |
|---|---|---|
| `POST` | `/projects/{project_id}/workflows/planning` | Start or queue Planning Workflow (Returns `202 Accepted` with `run_id` & interrupt state) |
| `GET` | `/projects/{project_id}/runs/{run_id}/tasks` | Retrieve implementation task list for a planning run |
| `PATCH` | `/projects/{project_id}/runs/{run_id}/tasks/{task_id}` | Edit task description/files/sequence or split task into subtasks |
| `POST` | `/projects/{project_id}/runs/{run_id}/approve` | Approve plan via REST fallback (unlocks code generation stage) |
| `POST` | `/projects/{project_id}/runs/{run_id}/reject` | Reject plan with feedback via REST fallback (triggers revision loop) |
| `GET` | `/projects/{project_id}/runs/{run_id}/patterns` | Retrieve selected design patterns |
| `GET` | `/projects/{project_id}/runs/{run_id}/research` | Retrieve multi-source research findings & citations |
| `GET` | `/projects/{project_id}/runs/{run_id}/architecture` | Retrieve generated architecture specification (JSON & Markdown) |
| `GET` | `/projects/{project_id}/runs/{run_id}/artifacts` | Consolidated endpoint for patterns, research, architecture, and tasks |
| `GET` | `/projects/{project_id}/runs/{run_id}/events` | SSE event stream for real-time progress updates |
| `WS` | `/projects/{project_id}/runs/{run_id}/hitl` | Dual-workflow WebSocket endpoint for interactive prompts & approval popups |

---

## 3. End-to-End Testing Procedure in Swagger UI

Open your browser at `http://127.0.0.1:8000/docs`.

### Step 3.1: Authenticate & Select/Create Project
1. Go to `POST /auth/register` or `POST /auth/token`.
2. Register/login with:
   ```json
   {
     "email": "planner@example.com",
     "password": "SecretPassword123!"
   }
   ```
3. Copy the returned `access_token`.
4. Click **Authorize** at the top of Swagger UI, paste the token into the `Bearer` input box, and click **Authorize**.
5. Create a project via `POST /projects`:
   ```json
   {
     "name": "Corporate Expense Platform",
     "description": "Milestone 4 Planning Test Project"
   }
   ```
   Note down the returned `project_id` (e.g., `PROJ-12345678`).

---

### Step 3.2: Upload Document or Ingest BRD
Upload a document via `POST /projects/{project_id}/documents`:
- Select a file (e.g. `expense_brd.md`).
- Click **Execute**. Note the returned `document_id` (e.g. `DOC-ABCD1234`).

---

### Step 3.3: Launch Planning Workflow
Navigate to `POST /projects/{project_id}/workflows/planning` in Swagger UI:
- Input JSON body using the document bridge:
  ```json
  {
    "document_ids": ["DOC-ABCD1234"]
  }
  ```
- Click **Execute**.
- Verify HTTP Response `202 Accepted` with payload containing `run_id`, `status: "RUNNING"`, `planning_route`, and interrupt prompt state.

---

### Step 3.4: Inspect Multi-Source Research & Selected Patterns
1. `GET /projects/{project_id}/runs/{run_id}/patterns`: Returns selected design patterns mapped to requirements with confidence scores.
2. `GET /projects/{project_id}/runs/{run_id}/research`: Returns parallel research findings tagged with `[doc:...]`, `[kb:...]`, `[web:...]`, and `[llm]`.
3. `GET /projects/{project_id}/runs/{run_id}/architecture`: Returns generated system components, data flows, and markdown specification.

---

### Step 3.5: Task Editing & Splitting
1. `GET /projects/{project_id}/runs/{run_id}/tasks`: Fetch initial tasks (e.g. `TASK-001`, `TASK-002`).
2. Edit Task Description / Target Files:
   `PATCH /projects/{project_id}/runs/{run_id}/tasks/TASK-001`
   ```json
   {
     "description": "Refactored SQLite repository layer with thread-safe connection pooling.",
     "target_files": ["app/repository.py", "app/database.py"]
   }
   ```
3. Split Task:
   `PATCH /projects/{project_id}/runs/{run_id}/tasks/TASK-002`
   ```json
   {
     "split_into": [
       {
         "title": "Subtask 2.1 — Authentication Middleware",
         "description": "Implement JWT verification middleware.",
         "target_files": ["app/auth.py"],
         "acceptance_criteria": ["Tokens validate successfully"]
       },
       {
         "title": "Subtask 2.2 — User Permission Checks",
         "description": "Implement RBAC helper functions.",
         "target_files": ["app/permissions.py"],
         "acceptance_criteria": ["Role permissions enforced"]
       }
     ]
   }
   ```

---

### Step 3.6: WebSocket HITL Approval Gate
Connect to WebSocket `ws://127.0.0.1:8000/projects/{project_id}/runs/{run_id}/hitl?token={JWT_TOKEN}`:
1. Receives `approval_request` prompt message with full summary (selected patterns, research, architecture components, tasks, validation results).
2. Send JSON response:
   ```json
   {
     "type": "approval_response",
     "decision": "APPROVE"
   }
   ```
3. Receive `workflow_resumed` and `run_completed` confirmation messages.

---

### Step 3.7: REST Fallback Approval / Rejection
Alternatively, approve/reject via REST endpoints:
- `POST /projects/{project_id}/runs/{run_id}/approve`
- `POST /projects/{project_id}/runs/{run_id}/reject` with body `{"feedback": "Add security review task."}`

---

## 4. Verification Checklist

- [x] Document-to-Requirements Bridge converts documents cleanly.
- [x] Pattern KB selection returns relevant patterns.
- [x] Multi-source parallel research generates verified citation tags.
- [x] Architecture design generates structured JSON & Markdown specs.
- [x] Task validation enforces requirement coverage, topological sequence ordering, atomicity, and citations.
- [x] Task PATCH endpoint supports description edits, reordering, and task splits.
- [x] Attempting task edits after approval returns `400 Bad Request`.
- [x] 100% pytest test suite passes (`111 passed`).
