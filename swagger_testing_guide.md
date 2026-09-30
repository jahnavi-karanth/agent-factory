# End-to-End Swagger & WebSocket Testing Guide
### Milestones 1, 2 & 3 — Agent Factory

> [!IMPORTANT]
> **Server Startup**: `uvicorn app.main:app --reload --port 8000`  
> **Swagger UI URL**: **http://localhost:8000/docs**  
> All endpoints are organized in Swagger UI under clean, expandable tags corresponding to system features.

---

## Guide Index & Swagger Group Mapping

| Swagger UI Group Tag | Feature Scope | Key Endpoints |
|---|---|---|
| **System & Infrastructure** | Pre-flight health checks & system status | `GET /health`, `GET /healthz` |
| **Authentication** | Registration, Login, Token generation | `POST /auth/register`, `POST /auth/login` |
| **Project Management** | Encapsulated workspaces & project lifecycle | `POST /projects`, `GET /projects`, `GET /projects/{id}` |
| **Document Management** | BRD upload, chunking, section extraction & RAG search | `POST /projects/{id}/documents`, `GET /documents`, `GET /search` |
| **Requirements Workflow (M1-M3)** | LangGraph workflow execution, HITL & artifact export | `POST /workflows/requirements`, `GET /runs/{id}`, `WS /hitl` |
| **Pattern Knowledge Base** | Seeded architecture patterns & semantic search | `GET /patterns`, `POST /patterns`, `POST /patterns/search` |
| **Legacy Standalone APIs (Deprecated)** | Standalone un-encapsulated APIs | `POST /api/brd/upload`, `POST /api/requirements/analyze` |

---

## Pre-Flight Checklist

Verify infrastructure status before running tests:

### Step 0.1 — Standard Health Check
```
GET /health
```
**Expected 200:**
```json
{ "status": "ok", "milestone": "BRD ingestion" }
```

### Step 0.2 — Deep Health Check
```
GET /healthz
```
**Expected 200:**
```json
{
  "status": "ok",
  "checks": {
    "sqlite": "ok",
    "chromadb": "ok",
    "filesystem": "ok"
  }
}
```

> [!CAUTION]
> If `chromadb` or `sqlite` fails, workflows will fail. Verify database connectivity before starting.

---

## SECTION 1 — Authentication (`/auth`)

### Step 1 — Register User
```
POST /auth/register
Content-Type: application/json

{
  "email": "test@factory.dev",
  "password": "SecurePass123!"
}
```
**Expected 201 Created:**
```json
{
  "user_id": "USR-XXXXXXXXXXXX",
  "email": "test@factory.dev",
  "access_token": "<jwt_token>",
  "token_type": "bearer"
}
```
**Save:** `ACCESS_TOKEN`

> [!NOTE]
> In Swagger UI, click the **Authorize** button at the top right and enter `Bearer <access_token>`. All protected endpoints require this authorization header.

#### Edge Case 1.1 — Duplicate Registration
```
POST /auth/register
{ "email": "test@factory.dev", "password": "SecurePass123!" }
```
**Expected 409 Conflict:** `email already registered`

---

### Step 2 — Login
```
POST /auth/login
{ "email": "test@factory.dev", "password": "SecurePass123!" }
```
**Expected 200 OK:**
```json
{ "access_token": "<jwt_token>", "token_type": "bearer" }
```

#### Edge Case 1.2 — Invalid Credentials
```
POST /auth/login
{ "email": "test@factory.dev", "password": "WrongPassword!" }
```
**Expected 401 Unauthorized:** `invalid credentials`

---

## SECTION 2 — Project Management (`/projects`)

### Step 3 — Create Project Workspace
```
POST /projects
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Corporate Expense Platform",
  "status": "draft"
}
```
**Expected 201 Created:**
```json
{
  "project_id": "PROJ-XXXXXXXXXXXX",
  "name": "Corporate Expense Platform",
  "status": "draft",
  "owner_id": "USR-XXXXXXXXXXXX"
}
```
**Save:** `PROJECT_ID`

#### Edge Case 2.1 — Invalid Status Value
```
POST /projects
{ "name": "Invalid Project", "status": "invalid_status_code" }
```
**Expected 422 Unprocessable Entity:** Validation error for `status`.

---

### Step 4 — List User Projects
```
GET /projects
Authorization: Bearer <token>
```
**Expected 200 OK:** Array of projects owned by the authenticated user.

---

### Step 5 — Get Project Details
```
GET /projects/{project_id}
Authorization: Bearer <token>
```
**Expected 200 OK:** Returns full project metadata object.

#### Edge Case 2.2 — Non-Existent Project
```
GET /projects/PROJ-DOESNOTEXIST
```
**Expected 404 Not Found**

---

### Step 6 — Update Project Status
```
PATCH /projects/{project_id}
Authorization: Bearer <token>
Content-Type: application/json

{ "status": "ready" }
```
**Expected 200 OK:** Updated project object with `"status": "ready"`.

---

## SECTION 3 — Document Management (`/projects/{project_id}/documents`)

### Step 7 — Upload BRD Document
In Swagger UI, select `POST /projects/{project_id}/documents`, specify `project_id`, and upload a document file (`.md`, `.pdf`, `.docx`, or `.txt`).

```
POST /projects/{project_id}/documents
Authorization: Bearer <token>
Content-Type: multipart/form-data
file: [BRD.md]
```
**Expected 201 Created:**
```json
{
  "document_id": "DOC-XXXXXXXXXXXX",
  "filename": "BRD.md",
  "status": "COMPLETED",
  "chunk_count": 28,
  "section_count": 6,
  "content_hash": "sha256:..."
}
```
**Save:** `DOCUMENT_ID`

#### Edge Case 3.1 — Duplicate Upload (Idempotency)
Re-upload the exact same file content into the same project.  
**Expected 200 OK** (Idempotent response, returns existing document record).

#### Edge Case 3.2 — Unsupported File Format
Upload a `.csv` or `.exe` file.  
**Expected 400 Bad Request:** `Unsupported file format`

#### Edge Case 3.3 — Empty File Upload
Upload a 0-byte file.  
**Expected 400 Bad Request:** `The uploaded document is empty`

---

### Step 8 — List Project Documents
```
GET /projects/{project_id}/documents
Authorization: Bearer <token>
```
**Expected 200 OK:** Array of document records encapsulated under `{project_id}`.

---

### Step 9 — Get Document Chunks & Sections
```
GET /projects/{project_id}/documents/{document_id}/sections
Authorization: Bearer <token>
```
**Expected 200 OK:** Parsed document sections with hierarchy and titles.

---

### Step 10 — Semantic Vector Search (RAG)
```
GET /projects/{project_id}/documents/search?q=authentication&limit=5
Authorization: Bearer <token>
```
**Expected 200 OK:** Vector search results matching query terms within project documents.

---

## SECTION 4 — Requirements Workflow (M1-M3)

### Step 11 — Trigger Project Requirements Workflow
Executes the unified LangGraph workflow (Ingestion → Analysis → Clarification HITL → Synthesis → Approval HITL → Artifact Export).

```
POST /projects/{project_id}/workflows/requirements
Authorization: Bearer <token>
Content-Type: application/json

{}
```
> [!NOTE]
> Leaving the request body `{}` automatically auto-discovers all completed documents uploaded to `{project_id}`.

**Expected 202 Accepted:**
```json
{
  "run_id": "RUN-XXXXXXXXXXXX",
  "project_id": "PROJ-XXXXXXXXXXXX",
  "brd_id": "BRD-XXXXXXXXXXXX",
  "status": "PAUSED",
  "interrupt": [
    {
      "type": "clarification_request",
      "request_id": "RUN-XXXXXXXXXXXX:clarification:0",
      "questions": [
        {
          "question_id": "QID-001",
          "question": "What authentication protocol is required?",
          "affected_requirements": ["REQ-002"]
        }
      ]
    }
  ]
}
```
**Save:** `RUN_ID`, `BRD_ID`

#### Edge Case 4.1 — Empty Project Workflow Trigger
Call workflow trigger on a project with no uploaded documents:  
**Expected 400 Bad Request:** `No document_ids provided and no completed documents found for project`

#### Edge Case 4.2 — Duplicate Concurrent Run
Trigger a second workflow while a run is active (`PAUSED`):  
**Expected 409 Conflict:** `active workflow run already exists`

---

## COMPREHENSIVE GUIDE: Testing Requirements & Ambiguity Questions

> [!IMPORTANT]
> ### Where do you find Ambiguity Questions asked by the AI?
> When the requirements analysis node detects missing specs, ambiguous priorities, or undefined architectural constraints, the workflow pauses and publishes the questions in **3 synchronous/asynchronous locations**:

1. **HTTP 202 Response Body**: Returned directly in the `interrupt[0].questions` array when calling `POST /projects/{project_id}/workflows/requirements` or `GET /projects/{project_id}/runs/{run_id}`.
2. **Server-Sent Events (SSE) Stream**: Emitted over `GET /projects/{project_id}/runs/{run_id}/events` as `clarification_required` event payload.
3. **Project-Bound WebSocket Channel**: Sent immediately upon connection to `WS /projects/{project_id}/runs/{run_id}/hitl?access_token=<token>` as a `{ type: "clarification_request", questions: [...] }` message.

---

### Phase A: Answering Clarification Questions

#### Method 1 — REST API (`POST /hitl/response`)
```
POST /projects/{project_id}/runs/{run_id}/hitl/response
Authorization: Bearer <token>
Content-Type: application/json

{
  "payload": [
    {
      "question_id": "QID-001",
      "answer": "Use OAuth2 with JWT Bearer tokens and RS256 signing."
    }
  ]
}
```
**Expected 200 OK:**
- If approval is needed next: `"status": "PAUSED"`, with `type: "approval_request"` in the `interrupt` list.
- If all questions resolved & approved: `"status": "COMPLETED"`.

#### Method 2 — Per-Run Interactive WebSocket (`WS /projects/{project_id}/runs/{run_id}/hitl`)

> [!TIP]
> **Why doesn't this show up in Swagger UI?**  
> OpenAPI / Swagger UI natively supports standard HTTP REST requests. WebSockets use a persistent `ws://` protocol connection. You can test WebSockets directly in your browser's Developer Tools Console (`F12` -> Console tab) on `http://localhost:8000/docs` using the interactive script below.

**Interactive Browser Console Script (Dynamic Popups, Non-Hardcoded Answers):**

Open Swagger UI (`http://localhost:8000/docs`), open Developer Console (`F12` or `Cmd+Option+I` -> **Console** tab), paste the snippet below, and hit Enter:

```javascript
// Step 1: Set your token and project/run IDs
const token = "<YOUR_JWT_ACCESS_TOKEN>"; // Token from /auth/login
const projectId = "<YOUR_PROJECT_ID>";     // e.g. PROJ-1B01144A7838
const runId = "<YOUR_RUN_ID>";           // e.g. RUN-XXXXXXXXXXXX

// Step 2: Establish the WebSocket connection
const wsUrl = `ws://localhost:8000/projects/${projectId}/runs/${runId}/hitl?access_token=${token}`;
console.log("Connecting to WebSocket:", wsUrl);

const ws = new WebSocket(wsUrl);

ws.onopen = () => console.log("🟢 Connected to HITL WebSocket stream!");

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log("📥 Received from Server:", data);

  // === CASE 1: Server asks Clarification Questions ===
  if (data.type === "clarification_request") {
    console.log(`❓ Received ${data.questions.length} question(s) from AI.`);
    
    const answers = [];
    for (const q of data.questions) {
      // DYNAMIC POPUP: Prompts you on screen for each question!
      const userAnswer = prompt(
        `[AI Ambiguity Question]\n\nRequirement Issue: ${q.question}\n\nPlease enter your answer/clarification below:`,
        ""
      );
      
      // If user clicks Cancel on question popup, stop and leave PAUSED
      if (userAnswer === null) {
        console.log("⚠️ Question prompt cancelled by user. Workflow remains PAUSED.");
        return;
      }

      answers.push({
        id: q.question_id,
        answer: userAnswer || "No answer provided"
      });
    }

    // Send dynamic answers back to server
    ws.send(JSON.stringify({ type: "clarification_response", answers }));
  }

  // === CASE 2: Server reaches Approval Gate ===
  if (data.type === "approval_request") {
    console.log(`📋 Approval Gate (Revision Count: ${data.revision_count}):`, data.requirements);
    
    // Format full Q&A Review Text
    const summary = data.clarification_summary || [];
    const reqs = data.requirements_summary || [];
    console.table("REVIEW OF ANSWERS:", summary);

    let reviewText = `=== REVIEW BEFORE APPROVAL (Revision ${data.revision_count}) ===\n\n`;
    if (summary.length > 0) {
      reviewText += "CLARIFICATION DECISIONS:\n";
      summary.forEach((item, idx) => {
        reviewText += `${idx + 1}. Q: ${item.question}\n   A: ${item.answer}\n`;
      });
    } else {
      reviewText += "No clarification questions were required.\n";
    }

    if (reqs.length > 0) {
      reviewText += "\nSYNTHESIZED REQUIREMENTS:\n";
      reqs.forEach(r => {
        reviewText += `- [${r.id}] (${r.type}): ${r.description}\n`;
      });
    }

    // DYNAMIC POPUP: Display full review text and ask for APPROVE / REJECT
    const decision = prompt(
      `${reviewText}\n-------------------------------------------\nType 'APPROVE' to accept, 'REJECT' to request revisions, or click Cancel to stay PAUSED:`,
      "APPROVE"
    );

    // If user clicked CANCEL, do NOT send any message to server (stay PAUSED)
    if (decision === null) {
      console.log("⚠️ Approval prompt cancelled by user. Workflow remains safely PAUSED.");
      return;
    }

    const trimmed = decision.trim().toUpperCase();
    if (trimmed === "REJECT") {
      const feedback = prompt("Enter revision feedback for the AI:", "Needs sub-200ms latency requirement.");
      if (feedback === null) {
        console.log("⚠️ Rejection feedback cancelled by user. Workflow remains PAUSED.");
        return;
      }
      ws.send(JSON.stringify({
        type: "approval_response",
        decision: "REJECT",
        feedback: feedback || "Revision requested"
      }));
    } else if (trimmed === "APPROVE") {
      ws.send(JSON.stringify({ type: "approval_response", decision: "APPROVE" }));
    } else {
      console.log(`⚠️ Unrecognized decision '${decision}'. Workflow remains PAUSED.`);
    }
  }

  // === CASE 3: Workflow Completed ===
  if (data.type === "completed") {
    alert(`🎉 Workflow Completed Successfully!\nRun ID: ${data.run_id}\nStatus: ${data.status}`);
    console.log("✅ Workflow execution finished successfully!");
    ws.close();
  }

  // === CASE 4: Error Received ===
  if (data.type === "error") {
    alert(`❌ Error from AI server: ${data.message}`);
    console.error("Server Error:", data);
  }
};

ws.onerror = (error) => console.error("❌ WebSocket Error:", error);
ws.onclose = (event) => console.log(`🔴 Connection closed. Code: ${event.code}, Reason: ${event.reason}`);
```

---

### Phase B: Handling Approval / Rejection Gate

Once ambiguities are clarified, the workflow reaches the **Approval Gate**.

#### Option B1 — APPROVE Workflow Output
```
POST /projects/{project_id}/runs/{run_id}/approve
Authorization: Bearer <token>
Content-Type: application/json

{ "payload": {} }
```
**Expected 200 OK:**
```json
{
  "run_id": "RUN-XXXXXXXXXXXX",
  "status": "COMPLETED",
  "interrupt": [],
  "state": { "status": "COMPLETED", "approval_status": "APPROVED" }
}
```

#### Option B2 — REJECT & Request Revision
```
POST /projects/{project_id}/runs/{run_id}/reject
Authorization: Bearer <token>
Content-Type: application/json

{
  "payload": {
    "feedback": "Please elaborate section 4.2 performance targets."
  }
}
```
**Expected 200 OK:** Workflow status resets to `PAUSED` and loops back for refinement.

---

### Step 12 — Retrieve Synthesized Project Requirements
```
GET /projects/{project_id}/requirements
Authorization: Bearer <token>
```
**Expected 200 OK:** Full, consolidated `RequirementsModel` extracted across all project documents:
```json
{
  "brd_id": "BRD-XXXXXXXXXXXX",
  "title": "Corporate Expense Management Platform",
  "business_problem": "...",
  "requirements": [
    {
      "id": "REQ-001",
      "description": "System must support expense filing via mobile.",
      "type": "functional",
      "priority": "high"
    }
  ]
}
```

---

### Step 13 — Retrieve Version History & Audit Logs
```
GET /projects/{project_id}/versions
Authorization: Bearer <token>
```
**Expected 200 OK:** List of requirement model revision versions.

```
GET /projects/{project_id}/audit
Authorization: Bearer <token>
```
**Expected 200 OK:** Security and compliance audit records for this project.

---

### Step 14 — Download Generated Final Artifacts
```
GET /projects/{project_id}/runs/{run_id}/artifacts
Authorization: Bearer <token>
```
**Expected 200 OK:**
```json
{
  "md_path": "data/projects/PROJ-.../runs/RUN-.../Requirements.md",
  "json_path": "data/projects/PROJ-.../runs/RUN-.../Requirements.json"
}
```

---

## SECTION 5 — Pattern Knowledge Base (`/patterns`)

### Step 15 — List Seeded Architecture Patterns
```
GET /patterns
Authorization: Bearer <token>
```
**Expected 200 OK:** Returns default pre-seeded patterns (loaded from `patterns.yaml`).

---

### Step 16 — Create Custom Pattern
```
POST /patterns
Authorization: Bearer <token>
Content-Type: application/json

{
  "name": "Event-Driven Saga Pattern",
  "category": "distributed_transactions",
  "description": "Coordinates transactions across microservices using event orchestrators.",
  "use_case": "Multi-stage payment workflows",
  "implementation_notes": "Use idempotent consumers.",
  "tags": ["saga", "events", "microservices"],
  "examples": ["Order processing pipeline"]
}
```
**Expected 201 Created:** `PatternModel` with `pattern_id: "PAT-XXXXXXXXXXXX"`.

#### Edge Case 5.1 — Duplicate Pattern Name
Re-submit same pattern name:  
**Expected 409 Conflict:** `Pattern with this name already exists`

---

### Step 17 — Semantic Vector Search over Patterns
```
POST /patterns/search
Authorization: Bearer <token>
Content-Type: application/json

{
  "query": "how to manage microservice authentication",
  "limit": 5
}
```
**Expected 200 OK:** Array of patterns ranked by vector similarity score.

---

### Step 18 — Update & Delete Pattern
```
PATCH /patterns/{pattern_id}
Authorization: Bearer <token>
Content-Type: application/json

{ "description": "Updated saga description." }
```
**Expected 200 OK:** Updated pattern metadata.

```
DELETE /patterns/{pattern_id}
Authorization: Bearer <token>
```
**Expected 200 OK:** Soft/hard deleted pattern record.

---

## SECTION 6 — Legacy Standalone APIs (Deprecated)

> [!NOTE]
> These endpoints support un-encapsulated standalone BRD analysis without project context. Prefer using `/projects/{project_id}/...` endpoints for production workflows.

### Step 19 — Standalone BRD Upload
```
POST /api/brd/upload
Content-Type: multipart/form-data
file: [BRD.md]
```
**Expected 200 OK:** `RequirementsModel` with generated `brd_id`.

---

### Step 20 — Standalone Manual Requirements Analysis
```
POST /api/requirements/analyze
Content-Type: application/json

{ "brd_id": "BRD-XXXXXXXXXXXX" }
```
**Expected 200 OK:** `RequirementsAnalysis` object containing `analysis_id` and completeness score.

---

### Step 21 — Standalone HITL Session & WebSocket
```
POST /api/hitl/session
Content-Type: application/json

{ "analysis_id": "ANA-XXXXXXXXXXXX" }
```
**Expected 200 OK:** Returns `session_id`. Connect via `ws://localhost:8000/ws/hitl/{session_id}`.

---

## SECTION 7 — System & Graph Utilities

### Step 22 — View LangGraph Workflow Diagram
```
GET /workflows/requirements/graph.png
```
**Expected 200 OK:** PNG visualization of the LangGraph state graph.

---

## Verification Matrix

| Step | Action | Endpoint | Expected Result |
|---|---|---|---|
| 1 | Health Check | `GET /healthz` | `200 OK` |
| 2 | Register | `POST /auth/register` | `201 Created` |
| 3 | Create Project | `POST /projects` | `201 Created` |
| 4 | Upload Document | `POST /projects/{id}/documents` | `201 Created` |
| 5 | Trigger Workflow | `POST /projects/{id}/workflows/requirements` | `202 Accepted` |
| 6 | Get Questions | HTTP Response / SSE / WS | Questions array |
| 7 | Submit Answers | `POST /projects/{id}/runs/{id}/hitl/response` | `200 OK` |
| 8 | Approve | `POST /projects/{id}/runs/{id}/approve` | `200 OK` |
| 9 | Get Artifacts | `GET /projects/{id}/runs/{id}/artifacts` | `200 OK` |
| 10 | Pattern Search | `POST /patterns/search` | `200 OK` |
