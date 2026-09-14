I want you to perform a COMPLETE, SYSTEMATIC TESTING AND VALIDATION of the current project implementation.

IMPORTANT: This is a TESTING task only. Do NOT implement new functionality, do NOT redesign the architecture, and do NOT start implementing future milestones just because you discover missing features.

The goal is to determine whether EVERYTHING THAT IS CURRENTLY IMPLEMENTED works correctly, including normal cases, failure cases, edge cases, persistence, state transitions, integration between milestones, and the newly implemented LangGraph-based M3 workflow.

==================================================

1. FIRST: INSPECT THE CURRENT IMPLEMENTATION
   ==================================================

Before running tests:

1. Inspect the complete repository structure.
2. Inspect the current implementation of:

   * API routes
   * Pydantic models
   * database models
   * migrations
   * services
   * BRD parser
   * requirement extractor
   * requirements model
   * requirements analyzer
   * HITL implementation
   * WebSocket implementation
   * LangGraph implementation
   * checkpointing
   * persistence
   * audit logging
   * configuration
   * Gemini provider abstraction
   * tests
3. Determine exactly which functionality is ACTUALLY implemented.
4. Do not assume that something is implemented merely because there is a placeholder, TODO, unused model, or configuration entry.
5. Run the existing test suite first and record the baseline.

Use the actual source code as the source of truth.

==================================================
2. TEST STATUS DEFINITIONS
==========================

For every feature/test, use one of these statuses:

* PASS = implemented and verified successfully
* FAIL = implemented but incorrect/broken
* NOT VERIFIED = appears implemented but could not be conclusively tested
* NOT IMPLEMENTED = clearly absent
* OUT OF SCOPE = intentionally excluded because it belongs to a future milestone

Do NOT mark future/unimplemented milestone functionality as FAIL.

At the end, clearly separate:

1. Actual bugs
2. Missing functionality
3. Not verified items
4. Out-of-scope future functionality

==================================================
3. USER MILESTONE 1 — BRD INGESTION + REQUIREMENTS MODEL
========================================================

Test ONLY the functionality that is currently implemented for BRD ingestion and Requirements Model generation.

---

## 3.1 BRD Upload

Test:

* valid Markdown upload
* valid TXT upload
* `.md`
* `.markdown`
* `.txt`
* empty file
* whitespace-only file
* malformed/invalid UTF-8 if the API accepts raw file bytes
* file exceeding configured maximum size
* very small valid document
* large valid document within the limit
* document containing:

  * Unicode
  * emojis
  * special characters
  * punctuation
  * numbers
  * URLs
  * code snippets
  * tables
  * long lines
  * repeated headings
  * duplicate content
  * unusual heading structures
* unsupported file extensions
* missing file
* malformed multipart request
* repeated upload of the same content
* repeated upload of the same filename
* concurrent uploads if the implementation allows this

Verify validation errors are structured and appropriate.

---

## 3.2 Parsing

Verify:

* Markdown headings are parsed correctly
* plain text is parsed correctly
* logical sections are created correctly
* section boundaries are correct
* line numbers/source locations are correct
* documents with no headings
* documents with only headings
* nested headings
* repeated headings
* unusual heading ordering
* blank sections
* very long sections
* special characters in headings
* Unicode headings
* content before the first heading
* trailing content
* malformed Markdown

Make sure parser failures do not silently corrupt the document.

---

## 3.3 Gemini Requirement Extraction

Verify:

* provider abstraction is actually used
* Gemini configuration comes from environment/configuration
* model names are NOT incorrectly hardcoded
* timeout handling
* retry handling
* fallback model behavior if implemented
* successful structured extraction
* empty model output
* malformed JSON
* incomplete JSON
* invalid schema
* missing required fields
* unexpected fields
* wrong data types
* duplicated requirements
* hallucinated/unsupported information
* model returning irrelevant content
* model timeout
* HTTP 429/quota failure
* HTTP 5xx
* provider/network failure
* repeated transient failures
* retries are bounded
* failures eventually return a controlled error
* application does not crash because of an LLM failure

Verify that extracted information remains grounded in the BRD.

---

## 3.4 Requirements Model

Verify all currently implemented fields, including:

* business problem
* objectives
* stakeholders
* user roles
* requirements
* non-functional requirements
* business rules
* constraints
* assumptions
* data requirements
* external dependencies
* success criteria

Test:

* missing optional information
* empty sections
* duplicate requirements
* invalid requirement objects
* malformed requirement objects
* stable sequential requirement IDs
* `REQ-001`, `REQ-002`, etc.
* source traceability
* requirement-to-source mapping
* validation failures
* persistence and retrieval

Ensure IDs are stable and not randomly regenerated on retrieval.

==================================================
4. USER MILESTONE 2 — REQUIREMENTS ANALYSIS
===========================================

The analyzer MUST consume the persisted Requirements Model from M1.

Verify that it does NOT unnecessarily:

* reparse the BRD
* re-extract requirements
* reinterpret raw BRD text
* regenerate the Requirements Model
* use human clarification answers as a substitute for the original M1 model

---

## 4.1 Analysis

Test detection of:

* ambiguity
* gaps
* conflicts
* inconsistencies

Test severity levels:

* LOW
* MEDIUM
* HIGH
* CRITICAL

Verify:

* correct requirement IDs are preserved
* issues map to the relevant requirements
* analysis summary is generated
* questions are generated only when appropriate
* questions are neutral and actionable
* unsupported technical decisions are not invented
* assumptions are not silently converted into requirements

---

## 4.2 Quality Status

Test every implemented quality status:

* INVALID
* NEEDS_REWORK
* READY_FOR_CLARIFICATION
* READY

Specifically verify:

* CRITICAL issues produce the correct blocking behavior
* question limit is enforced
* excessive questions cause the expected quality status
* no questions + no blocking issues produces the correct status
* material uncertainty is handled correctly
* blocking issues are accurately reported

---

## 4.3 Question Handling

Test:

* canonical question IDs such as `Q-001`
* sequential question IDs
* question-to-requirement mapping
* duplicate questions
* empty questions
* malformed questions
* too many questions
* maximum configured question count
* boundary conditions around the maximum
* persisted questions can be retrieved correctly

---

## 4.4 Persistence and Audit

Verify persistence of:

* analysis
* issues
* issue/requirement mappings
* clarification questions
* question/requirement mappings
* audit events

Test persistence across:

* normal restart
* DB reconnect
* repeated retrieval
* multiple analyses
* invalid analysis attempts

==================================================
5. M1 → M2 INTEGRATION
======================

Test the complete dependency chain:

BRD upload
→ parsing
→ requirement extraction
→ Requirements Model persistence
→ Requirements Analysis
→ persisted analysis
→ clarification questions

Verify that:

* M2 uses the correct persisted M1 Requirements Model
* requirement IDs remain consistent
* source traceability survives the transition
* analysis references the correct BRD/version
* no data is silently lost
* failures in M1 are handled correctly by M2
* nonexistent/invalid Requirements Model IDs are rejected
* wrong BRD/model combinations are rejected
* duplicate/repeated analysis requests behave consistently

==================================================
6. USER MILESTONE 3 — HITL CLARIFICATION
========================================

Test every currently implemented HITL capability.

---

## 6.1 HITL Session Creation

Verify:

* session can only be created when appropriate
* `READY_FOR_CLARIFICATION` behaves correctly
* no-question analysis does not incorrectly create a session
* invalid analysis ID is rejected
* session persistence works
* session state is correct

---

## 6.2 WebSocket

Test:

* connection
* initial session state
* question delivery
* sequential question delivery
* answer submission
* completion
* reconnect
* disconnect during a question
* disconnect after answer
* reconnect after disconnect
* invalid message type
* malformed JSON
* missing fields
* extra fields
* invalid question ID
* answering an already answered question
* answering out of order
* duplicate answers
* multiple simultaneous connections if supported
* connection to nonexistent session
* unauthorized access if authorization exists

Verify that WebSocket failures do not corrupt persisted state.

---

## 6.3 Answer Validation

Test:

* empty answer
* whitespace-only answer
* very short answer
* meaningful answer
* long answer
* irrelevant answer
* unrelated answer
* undecided response
* special characters
* Unicode
* contradictory answer
* repeated answer
* answer containing prompt-injection-style instructions

Verify that invalid answers trigger the correct behavior and do not accidentally advance the workflow.

---

## 6.4 Follow-Up Questions

Test:

* valid follow-up
* invalid answer causing follow-up
* maximum follow-up round
* exactly at maximum
* exceeding maximum
* repeated poor answers
* follow-up generation failure
* malformed follow-up output
* follow-up persistence
* reconnect during follow-up
* no unnecessary rerun of M2

Verify that follow-ups remain grounded in:

* Requirements Model
* original analysis
* human answers
* detected flags/issues

---

## 6.5 Undecided Answers / AI Best Decision

Test:

* user provides a clear answer
* user explicitly says undecided
* AI recommendation is generated
* AI recommendation generation fails
* recommendation is malformed
* multiple undecided questions
* human answer conflicts with AI recommendation

Verify the intended precedence rules.

Human-provided decisions must not be silently overridden by AI recommendations.

---

## 6.6 Resolved Requirements Model

Verify:

* resolved model is persisted
* original Requirements Model remains intact
* human answers are represented correctly
* AI decisions/recommendations are represented correctly
* resolved data can be retrieved
* requirement IDs remain stable
* source traceability is preserved
* no unrelated fields are accidentally changed
* repeated retrieval returns the same resolved result

If the current implementation materializes answers/decisions into canonical fields such as requirements, business rules, constraints, or success criteria, test those mappings thoroughly.

==================================================
7. LANGGRAPH-BASED M3 — TEST ONLY WHAT IS ACTUALLY IMPLEMENTED
==============================================================

Inspect the current LangGraph implementation first.

For every LangGraph feature that exists, test it thoroughly.

---

## 7.1 StateGraph

Verify:

* graph construction
* state schema
* state initialization
* state updates
* node execution
* edge transitions
* terminal state
* invalid state handling
* missing state fields
* unexpected state values

---

## 7.2 Nodes and Edges

Test every implemented node individually where practical.

Verify:

* correct input
* correct output
* correct transition
* error handling
* retry behavior if implemented
* terminal behavior
* conditional routing if implemented

Test every implemented conditional branch.

Explicitly test:

* normal branch
* alternate branch
* invalid branch condition
* boundary condition
* unexpected state

---

## 7.3 interrupt()

If `interrupt()` is implemented, verify:

* workflow pauses exactly where expected
* interrupt payload is correct
* state is preserved
* client receives the expected HITL request
* workflow does not continue without resume
* resume continues from the correct point
* repeated resume does not corrupt state

---

## 7.4 Command(resume=...)

If implemented, test:

* valid resume
* resume with expected answer
* resume with invalid data
* resume after disconnect
* resume after application restart
* duplicate resume
* resume on already-completed workflow
* resume with wrong run/session
* resume after checkpoint restoration

Verify that execution resumes from the correct graph state rather than restarting unnecessarily.

---

## 7.5 Checkpointing

If LangGraph checkpointing is implemented, test:

* checkpoint creation
* checkpoint persistence
* checkpoint retrieval
* resume from checkpoint
* process restart
* DB reconnect
* disconnect/reconnect
* paused graph
* completed graph
* failed graph
* duplicate resume
* stale checkpoint
* missing checkpoint
* corrupted checkpoint handling if practical

Verify that checkpoint state belongs to the correct workflow/run/thread.

---

## 7.6 Project/Run Scoping

ONLY IF THIS HAS ACTUALLY BEEN IMPLEMENTED, test:

* project creation
* project isolation
* run creation
* project-scoped run retrieval
* project-scoped HITL
* wrong project ID
* wrong run ID
* cross-project access
* cross-run access
* nonexistent project
* nonexistent run
* concurrent runs

Verify no state, artifact, or session leaks between projects/runs.

---

## 7.7 Approval / Rejection Gate

ONLY IF IMPLEMENTED, test:

* approval request
* approval response
* approve
* reject
* reject with feedback
* approval after disconnect
* approval after restart
* duplicate approval
* duplicate rejection
* invalid approval state
* approval after completion
* rejection after completion
* revision after rejection
* resume from the correct previous graph node

Verify that rejection does NOT incorrectly restart the entire workflow if the intended implementation supports targeted revision.

---

## 7.8 REST Fallback

ONLY IF IMPLEMENTED, test:

* REST approval
* REST rejection
* REST clarification
* malformed request
* invalid state
* duplicate request
* wrong run/session
* interaction between REST and WebSocket clients

Verify REST and WebSocket paths cannot cause conflicting state transitions.

---

## 7.9 SSE

ONLY IF IMPLEMENTED, test:

* connection
* event delivery
* event ordering
* event types
* reconnection
* completed workflow
* failed workflow
* disconnected client
* multiple listeners
* duplicate events
* malformed event payloads

==================================================
8. ADVERSARIAL EDGE-CASE TESTING
================================

Now perform adversarial testing against EVERY IMPLEMENTED FEATURE above.

Do not restrict testing to happy paths.

---

## 8.1 Input Boundaries

For every applicable endpoint/function, test:

* empty input
* whitespace-only input
* minimum valid input
* maximum valid input
* one unit beyond maximum
* missing field
* null field
* wrong type
* empty array
* empty object
* extremely long string
* Unicode
* emoji
* special characters
* escaped characters
* duplicate values
* duplicate objects
* malformed JSON
* unexpected extra fields
* unexpected enum values
* negative numbers
* zero
* very large numbers
* invalid IDs
* nonexistent IDs

---

## 8.2 State Transition Abuse

Attempt invalid state transitions such as:

* answer before question
* answer after completion
* approval before approval request
* rejection after approval
* duplicate approval
* duplicate rejection
* resume before interrupt
* resume after completion
* resume twice
* answer the same question twice
* skip required question
* answer questions out of order
* create duplicate sessions
* restart completed workflow
* operate on failed workflow

Verify state remains consistent.

---

## 8.3 Idempotency / Duplication

Test repeated:

* uploads
* analysis requests
* session creation
* answers
* follow-ups
* resumes
* approvals
* rejections
* retrievals

Verify duplicate operations do not create corrupt or contradictory state.

---

## 8.4 Concurrency / Race Conditions

Where practical, test:

* two answers arriving simultaneously
* two clients connected to the same HITL session
* duplicate resume commands
* simultaneous approval/rejection
* simultaneous session creation
* simultaneous workflow execution
* concurrent DB access

Look for:

* duplicate records
* lost updates
* invalid state
* inconsistent audit logs
* deadlocks
* crashes

---

## 8.5 Disconnect / Recovery

Test disconnection at every important point:

* before first question
* while waiting for answer
* after answer
* during follow-up
* during AI processing
* while interrupted
* during approval
* after approval
* after rejection
* after workflow completion

Then reconnect/recover and verify state consistency.

---

## 8.6 Persistence Boundaries

Test:

* application restart during workflow
* application restart while interrupted
* DB reconnect
* retrieval after restart
* incomplete transactions
* repeated requests after restart
* checkpoint restoration
* session restoration

Verify no information is silently lost.

---

## 8.7 LLM Failure Testing

Simulate or mock:

* timeout
* HTTP 429
* HTTP 500
* HTTP 502
* HTTP 503
* network failure
* empty response
* malformed JSON
* invalid schema
* irrelevant response
* incomplete response
* hallucinated content
* repeated transient failure
* permanent failure

Verify:

* bounded retries
* fallback behavior if implemented
* controlled failure
* no infinite loops
* no corrupted DB state
* no partially committed invalid model output

---

## 8.8 Security / Isolation

Test applicable protections against:

* unauthorized access
* invalid IDs
* cross-session access
* cross-project access if projects exist
* tampered identifiers
* prompt injection inside BRD content
* prompt injection inside clarification answers
* malicious strings
* path traversal attempts
* unsafe filenames
* oversized payloads
* malformed WebSocket messages

Verify user-controlled content cannot cause unintended system behavior.

==================================================
9. DATABASE CONSISTENCY
=======================

Verify relationships between all implemented tables.

Check for:

* orphaned records
* missing foreign-key relationships
* duplicate records
* inconsistent statuses
* missing audit entries
* incorrect timestamps
* incorrect version references
* incorrect requirement mappings
* incorrect question mappings
* inconsistent session state
* inconsistent resolved-model state
* inconsistent LangGraph checkpoint state if implemented

If the project uses migrations, verify the current database can be created/upgraded cleanly.

==================================================
10. REGRESSION TESTING
======================

Run the complete existing test suite.

Then run any newly created tests.

Verify that changes related to LangGraph/HITL did not break:

* BRD upload
* parsing
* extraction
* Requirements Model
* Requirements Analysis
* question generation
* persistence
* existing APIs
* existing WebSocket behavior

==================================================
11. COMPLETE END-TO-END TEST
============================

Run the complete currently implemented workflow from beginning to end:

BRD upload
→ parse
→ Gemini extraction
→ Requirements Model
→ Requirements Analysis
→ clarification questions
→ HITL session
→ WebSocket interaction
→ follow-up if required
→ human answer / undecided behavior
→ resolved Requirements Model
→ LangGraph interrupt/resume if implemented
→ approval/rejection if implemented
→ persistence
→ final retrieval

Test both:

A. Successful path

and

B. Failure/recovery path

For the failure/recovery path, intentionally interrupt/disconnect/restart/fail at appropriate points and verify recovery.

==================================================
12. DO NOT TEST FUTURE / UNIMPLEMENTED FUNCTIONALITY
====================================================

The following are OUT OF SCOPE unless they are genuinely already implemented in the repository.

DO NOT implement them.

DO NOT report them as failures.

Specifically exclude:

* Pattern KB
* Pattern CRUD
* Pattern bulk import
* Chroma `patterns` collection
* pattern embeddings
* pattern search
* pattern RAG
* pattern ranking
* pattern selection
* architecture generation
* planning workflow
* project planning
* code generation
* developer agents
* reviewer agents
* generated-code testing agents
* future M4/M5/M6/M7 functionality

Also do NOT test official M1 features that are not actually implemented, such as:

* PDF ingestion
* DOCX ingestion
* PPTX ingestion
* XLSX ingestion
* Chroma `documents` collection
* full official project/auth lifecycle

Only test them if the current repository genuinely implements them.

==================================================
13. TEST IMPLEMENTATION QUALITY
===============================

While testing, also inspect for:

* swallowed exceptions
* overly broad exception handlers
* infinite retry loops
* hardcoded configuration
* hardcoded model names
* inconsistent error formats
* state mutation before validation
* partial database writes
* missing transaction boundaries
* race conditions
* incorrect async handling
* blocking operations inside async paths
* leaked resources
* incorrect WebSocket lifecycle handling
* incorrect checkpoint handling
* incorrect graph state mutation
* missing audit events
* inconsistent status transitions
* security-sensitive logging
* sensitive information accidentally logged

Do not refactor the project during this task unless absolutely necessary to create a minimal test harness. Report discovered issues instead.

==================================================
14. TEST REPORT
===============

At the end, produce a detailed report containing:

### A. Baseline

* existing tests before testing
* existing failures, if any

### B. Implemented Functionality Verified

For each feature:

* feature
* test performed
* result
* evidence

### C. Bugs Found

For every FAIL:

* exact functionality
* reproduction steps
* expected behavior
* actual behavior
* likely root cause
* severity:

  * CRITICAL
  * HIGH
  * MEDIUM
  * LOW

### D. Edge Cases

List all adversarial edge cases tested and their results.

### E. Persistence / Recovery

Report:

* restart tests
* disconnect tests
* checkpoint tests
* DB consistency tests
* recovery results

### F. Integration

Report:

* M1 → M2
* M2 → M3
* M3 HITL
* LangGraph integration
* approval/rejection if implemented

### G. Security

Report security/isolation findings.

### H. NOT VERIFIED

List functionality that appears implemented but could not be conclusively tested and explain why.

### I. NOT IMPLEMENTED / OUT OF SCOPE

Clearly list future functionality that was intentionally not tested.

### J. Final Summary

Provide:

* Total tests executed
* PASS count
* FAIL count
* NOT VERIFIED count
* NOT IMPLEMENTED count
* OUT OF SCOPE count
* Critical issues
* High-priority issues
* Recommended fixes

IMPORTANT FINAL RULE:

Do not tell me that the project "passes" merely because the existing tests pass.

You must independently test the implemented behavior, including negative cases, boundary cases, state-transition abuse, persistence/recovery, concurrency where practical, LLM failures, WebSocket failures, and LangGraph interruption/resumption.

The objective is to find real bugs in the CURRENT implementation, not to prove that the implementation is correct.
