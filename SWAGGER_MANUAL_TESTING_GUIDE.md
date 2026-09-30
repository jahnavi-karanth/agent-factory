# End-to-End Manual Testing Guide via Swagger UI & WebSocket

This guide provides step-by-step instructions for manually executing and validating all implemented workflows (**Milestone 1 BRD Ingestion**, **Milestone 2 Requirements Analysis**, and **Milestone 3 HITL & LangGraph Workflows**) using the Swagger UI interface and the Browser Console for WebSockets.

---

## 0. Prerequisites & Server Setup

1. **Start the FastAPI Backend**:
   Open a terminal in the project root `/Users/jahnavikaranth/Desktop/agent-factory` and run:
   ```bash
   uv run uvicorn app.main:app --reload --port 8000
   ```

2. **Access Swagger UI**:
   Open your browser and navigate to:
   [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)

---

## Step 1: User Registration & Authentication (JWT)

All protected project and workflow endpoints require a valid JWT Bearer token.

### 1.1 Register a User
- Locate **`POST /auth/register`** in Swagger.
- Click **Try it out**.
- Enter JSON payload:
  ```json
  {
    "email": "tester@example.com",
    "password": "Password123!"
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `201 Created` returning `user_id`, `email`, and `access_token`.

### 1.2 Authorize in Swagger UI
- Copy the returned `access_token` string.
- Scroll to the top of the Swagger page and click the green **Authorize** button.
- Paste the token into the **Value** input field.
- Click **Authorize**, then click **Close**.

*(Negative Test: Executing `POST /auth/register` again with the same email returns HTTP `409 Conflict`.)*

---

## Step 2: Create a Project Aggregate

All documents and workflow runs must be scoped under a project.

- Locate **`POST /projects`** in Swagger.
- Click **Try it out**.
- Enter JSON payload:
  ```json
  {
    "name": "Corporate Expense Management Refactor"
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `201 Created` returning a `project_id` (e.g., `PROJ-A1B2C3D4E5F6`).
- **Save this `project_id`** for subsequent steps.

---

## Step 3: Ingest a BRD Document (Milestone 1)

### 3.1 Happy Path Upload
- Locate **`POST /api/brd/upload`** in Swagger.
- Click **Try it out**.
- Set `project_id` parameter: `PROJ-A1B2C3D4E5F6`.
- For `file`, choose a Markdown file (e.g. `Business Requirements Document — Corporate Expense Management Platform.md`).
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning `brd_id` (e.g., `BRD-123456789ABC`), structured requirements array (`REQ-001`, `REQ-002`, etc.), and source references.
- **Save this `brd_id`**.

### 3.2 Verify Version & Retrieval
- **`GET /api/brd/{brd_id}/requirements`**: Enter `brd_id` -> Returns HTTP `200 OK` with requirements model.
- **`GET /api/brd/{brd_id}/versions`**: Enter `brd_id` -> Returns HTTP `200 OK` showing Version 1 with status `READY`.

### 3.3 Negative Upload Cases
- **Unsupported Format**: Upload a `.pdf` or `.png` file -> Returns HTTP `400 Bad Request` (`"unsupported BRD format"`).
- **Empty File**: Upload a `0 byte` file -> Returns HTTP `400 Bad Request` (`"BRD document is empty"`).

---

## Step 4: Run Requirements Analysis (Milestone 2)

### 4.1 Trigger Analysis
- Locate **`POST /api/requirements/analyze`** in Swagger.
- Click **Try it out**.
- Enter JSON payload:
  ```json
  {
    "brd_id": "BRD-123456789ABC"
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning `analysis_id` (e.g. `ANALYSIS-987654321DEF`), `quality_status`: `"READY_FOR_CLARIFICATION"`, issues, and clarification questions (`Q-001`, etc.).
- **Save this `analysis_id`**.

### 4.2 Verify Persistence & Audit Trail
- **`GET /api/analysis/{analysis_id}`**: Enter `analysis_id` -> Returns stored analysis model.
- **`GET /api/audit`**: Set `entity_id` = `BRD-123456789ABC` -> Returns audit events: `BRD_UPLOADED`, `ANALYSIS_STARTED`, `ANALYSIS_COMPLETED`.

---

## Step 5: HITL Clarification Loop over WebSocket (Milestone 3)

### 5.1 Create HITL Session via REST
- Locate **`POST /api/hitl/session`** in Swagger.
- Click **Try it out**.
- Enter JSON payload:
  ```json
  {
    "analysis_id": "ANALYSIS-987654321DEF"
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning `session_id` (e.g. `HITL-F1E2D3C4B5A6`), status `"ACTIVE"`.
- **Save this `session_id`**.

*(Negative Test: Calling `POST /api/hitl/session` for a `READY` analysis with no questions returns HTTP `409 Conflict`.)*

### 5.2 Interact over WebSocket (Browser Console)
1. Open your browser Developer Tools (**F12** or **Option+Cmd+I** on Mac).
2. Switch to the **Console** tab.
3. Replace `HITL-F1E2D3C4B5A6` with your actual session ID and run this snippet:

```javascript
const sessionId = "HITL-F1E2D3C4B5A6"; // Replace with your session_id
const ws = new WebSocket(`ws://127.0.0.1:8000/ws/hitl/${sessionId}`);

ws.onopen = () => console.log("%c[WS Connected]", "color: green; font-weight: bold;");

ws.onmessage = (event) => {
  const msg = JSON.parse(event.data);
  console.log("%c[WS Received]:", "color: blue;", msg);

  if (msg.type === "question") {
    const q = msg.question;
    const answer = prompt(`Question ID: ${q.question_id}\n\n${q.question}\n\nEnter your answer:`);
    if (answer && answer.trim()) {
      const reply = {
        type: "answer",
        question_id: q.question_id,
        answer: answer.trim()
      };
      console.log("%c[WS Sending]:", "color: orange;", reply);
      ws.send(JSON.stringify(reply));
    }
  } else if (msg.type === "completed") {
    console.log("%c[WS Completed] Session finished!", "color: green; font-weight: bold;");
  }
};

ws.onclose = () => console.log("%c[WS Closed]", "color: red;");
```

4. **Expected Sequence in Console**:
   - `type: "resumed"`
   - `type: "question"` (Prompts in browser alert)
   - Type a detailed answer: `"The manager approval threshold is specified as five hundred dollars per transaction."`
   - `type: "answer_acknowledged"`
   - `type: "completed"`

5. **Verify Resolved Model**:
   - Go back to Swagger and execute `GET /api/brd/{brd_id}/requirements`.
   - Notice `extraction_metadata` now contains `"resolved": "true"`.

---

## Step 6: LangGraph Requirements Workflow Execution (Milestone 3)

### 6.1 Start Workflow
- Locate **`POST /projects/{project_id}/workflows/requirements`**.
- Click **Try it out**.
- Parameters:
  - `project_id`: `PROJ-A1B2C3D4E5F6`
- Request body:
  ```json
  {
    "brd_id": "BRD-123456789ABC"
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `202 Accepted` returning `run_id` (e.g. `RUN-777888999AAA`), `status`: `"PAUSED"`, and interrupt details for clarification.
- **Save this `run_id`**.

### 6.2 View SSE Events Stream
- Open a new browser tab and visit:
  `http://127.0.0.1:8000/projects/PROJ-A1B2C3D4E5F6/runs/RUN-777888999AAA/events`
- **Expected Output**: Server-Sent Event stream emitting `workflow_started` and `clarification_required`.

### 6.3 Resume Clarification via REST Fallback
- Locate **`POST /projects/{project_id}/runs/{run_id}/hitl/response`**.
- Parameters: `project_id`, `run_id`.
- Request body:
  ```json
  {
    "payload": [
      {
        "question_id": "Q-001",
        "answer": "The manager threshold is set to five hundred dollars."
      }
    ]
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning `status`: `"PAUSED"`, moving graph execution to the `approval_gate`.

### 6.4 Test Rejection & Revision Loop Gate
- Locate **`POST /projects/{project_id}/runs/{run_id}/approval`**.
- Parameters: `project_id`, `run_id`.
- Request body (Rejection with feedback):
  ```json
  {
    "payload": {
      "decision": "REJECT",
      "feedback": "Add SLA requirement of 24 hours for approval escalation."
    }
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning `status`: `"PAUSED"`, `revision_count`: `1`. Graph re-routes back through resolution.

### 6.5 Final Approval Gate
- Call **`POST /projects/{project_id}/runs/{run_id}/approval`** again.
- Request body (Approval):
  ```json
  {
    "payload": {
      "decision": "APPROVE"
    }
  }
  ```
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning `status`: `"COMPLETED"`.

### 6.6 Retrieve Workflow Artifacts
- Locate **`GET /projects/{project_id}/runs/{run_id}/artifacts`**.
- Parameters: `project_id`, `run_id`.
- Click **Execute**.
- **Expected Result**: HTTP `200 OK` returning file paths:
  - `data/projects/PROJ-A1B2C3D4E5F6/runs/RUN-777888999AAA/Requirements.md`
  - `data/projects/PROJ-A1B2C3D4E5F6/runs/RUN-777888999AAA/Requirements.json`

---

## Step 7: Security & Cross-Project Isolation Checks

1. **Unauthenticated Request**:
   - Click **Authorize** -> **Logout**.
   - Execute `POST /projects` -> Returns HTTP `401 Unauthorized` (`"Bearer token required"`).

2. **Cross-Project Run Leakage Protection**:
   - Re-authorize with JWT.
   - Execute `GET /projects/PROJ-OTHER123/runs/{run_id}` -> Returns HTTP `404 Not Found` (avoids leaking existence across project boundaries).

---

## Summary Checklist for Acceptance

- [x] Auth JWT login & registration (`POST /auth/register`, `POST /auth/token`)
- [x] Project creation (`POST /projects`)
- [x] Document upload & parsing (`POST /api/brd/upload?project_id=...`)
- [x] Requirement model retrieval & version history (`GET /api/brd/{id}/requirements`, `versions`)
- [x] Requirements analysis (`POST /api/requirements/analyze`)
- [x] Audit logs (`GET /api/audit`)
- [x] HITL session creation (`POST /api/hitl/session`)
- [x] WebSocket interactive clarification (`WS /ws/hitl/{session_id}`)
- [x] LangGraph execution & interrupts (`POST /projects/{id}/workflows/requirements`)
- [x] SSE event stream (`GET /projects/{id}/runs/{id}/events`)
- [x] Rejection loop & revision routing (`POST /projects/{id}/runs/{id}/approval`)
- [x] Final approval & Markdown/JSON artifact generation (`GET /projects/{id}/runs/{id}/artifacts`)
