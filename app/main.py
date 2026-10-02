from __future__ import annotations

import json
import hashlib
import logging
import os
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()

from fastapi import Body, Depends, FastAPI, File, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .llm import ExtractionError
from .analysis_models import RequirementsAnalysis
from .analyzer import RequirementsAnalyzer
from .models import ErrorResponse, HealthResponse, RequirementsModel
from .parser import parse_document, extract_sections_and_chunks, SUPPORTED_EXTENSIONS
from .repository import PersistenceError, SQLiteRepository
from .service import IngestionService
from .workflow import RequirementsWorkflow
from .document_store import DocumentStore
from .auth import create_token, current_user, decode_token, hash_password, verify_password
from .filestore import FileStore
from .pattern_models import (
    PatternCreateRequest,
    PatternModel,
    PatternSearchRequest,
    PatternSearchResult,
    PatternUpdateRequest,
)
from .pattern_service import PatternService
from .planning_models import PlanningWorkflowRequest, RejectionRequest, TaskPatchRequest
from .planning_workflow import PlanningWorkflow



logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
VALID_PROJECT_STATUSES = {"draft", "ready", "running", "archived"}


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    brd_id: Optional[str] = None


class HITLSessionRequest(BaseModel):
    analysis_id: str


class ProjectRequest(BaseModel):
    name: str
    status: Optional[str] = "draft"
    owner_id: Optional[str] = None


class ProjectUpdateRequest(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None


class RequirementsWorkflowRequest(BaseModel):
    document_ids: List[str] = []
    brd_id: Optional[str] = None


class WorkflowResumeRequest(BaseModel):
    payload: Any


class AuthRequest(BaseModel):
    email: str
    password: str



def create_app(
    service: Optional[IngestionService] = None,
    analyzer: Optional[RequirementsAnalyzer] = None,
    repository: Optional[SQLiteRepository] = None,
    document_store: Optional[DocumentStore] = None,
    pattern_service: Optional[PatternService] = None,
) -> FastAPI:
    tags_metadata = [
        {"name": "Authentication", "description": "User registration and JWT token management"},
        {"name": "Project Management", "description": "Project creation, listing, retrieval, and status updates"},
        {"name": "Document Management", "description": "Document upload, structure parsing, outline sections, and semantic search"},
        {"name": "Requirements Workflow (M1-M3)", "description": "Project-bound LangGraph requirements workflow, per-run WebSocket HITL, SSE progress events, and artifact generation"},
        {"name": "Planning Workflow (M4)", "description": "Combined Project & Code Planning Workflow: pattern selection, multi-source research, architecture, task planning, quality validation, and HITL approval gate"},
        {"name": "Pattern Knowledge Base", "description": "Agentic design pattern repository management and embedding search"},
        {"name": "System & Infrastructure", "description": "Health diagnostics and LangGraph diagram visualization"},
        {"name": "Legacy Standalone APIs (Deprecated)", "description": "Un-scoped legacy endpoints retained for backward compatibility"},
    ]
    app = FastAPI(
        title="AI Agent Factory v2",
        version="0.2.0",
        description="Document-Driven, Pattern-Aware Code Generator (Backend-Only)",
        openapi_tags=tags_metadata,
    )
    ingestion = service or IngestionService()
    requirements_analyzer = analyzer or RequirementsAnalyzer()
    artifacts = repository or SQLiteRepository()
    workflow = RequirementsWorkflow(artifacts, requirements_analyzer)
    documents = document_store or DocumentStore()
    filestore = FileStore()
    patterns_svc = pattern_service or PatternService(repository=artifacts, document_store=documents)
    patterns_svc.seed_initial_patterns()
    planning_wf = PlanningWorkflow(artifacts, document_store=documents, pattern_service=patterns_svc)


    def interrupt_values(result: Dict[str, Any]) -> list[Any]:
        return [item.value if hasattr(item, "value") else item for item in result.get("__interrupt__", [])]

    @app.post("/auth/register", status_code=201, tags=["Authentication"])
    async def register(request: AuthRequest) -> Dict[str, Any]:
        user_id = "USR-" + uuid.uuid4().hex[:12].upper()
        try:
            user = artifacts.create_user(user_id, request.email, hash_password(request.password))
            return {**user, "access_token": create_token(user_id), "token_type": "bearer"}
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/auth/token", tags=["Authentication"])
    async def login(request: AuthRequest) -> Dict[str, Any]:
        try:
            user = artifacts.get_user_by_email(request.email)
            if not verify_password(request.password, user["password_hash"]):
                raise HTTPException(status_code=401, detail="invalid credentials")
            return {"access_token": create_token(user["user_id"]), "token_type": "bearer"}
        except PersistenceError as exc:
            raise HTTPException(status_code=401, detail="invalid credentials") from exc

    @app.post("/auth/login", tags=["Authentication"])
    async def auth_login(request: AuthRequest) -> Dict[str, Any]:
        return await login(request)

    @app.post("/projects", status_code=201, tags=["Project Management"])
    async def create_project(request: ProjectRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        status = request.status or "draft"
        if status not in VALID_PROJECT_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid project status '{status}'. Must be one of: {sorted(VALID_PROJECT_STATUSES)}")
        project_id = "PROJ-" + uuid.uuid4().hex[:12].upper()
        try:
            proj = artifacts.create_project(project_id, request.name, user_id, status=status)
            artifacts.audit("PROJECT_CREATED", "project", project_id, actor_id=user_id, details={"name": request.name, "status": status})
            return proj
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/projects", tags=["Project Management"])
    async def list_projects(user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        return artifacts.list_projects(user_id)

    @app.get("/projects/{project_id}", tags=["Project Management"])
    async def get_project(project_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            return artifacts.get_project(project_id, user_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/projects/{project_id}", tags=["Project Management"])
    async def update_project(project_id: str, request: ProjectUpdateRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        if request.status is not None and request.status not in VALID_PROJECT_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid project status '{request.status}'. Must be one of: {sorted(VALID_PROJECT_STATUSES)}")
        try:
            return artifacts.update_project(project_id, user_id, name=request.name, status=request.status)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/documents/search", tags=["Document Management"])
    async def search_project_documents(project_id: str, q: str, limit: int = 5, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return documents.search(project_id, q, max(1, min(limit, 20)))
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/documents", tags=["Document Management"])
    async def list_project_documents(project_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.list_documents(project_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/documents", status_code=201, tags=["Document Management"])
    async def upload_project_document(project_id: str, file: UploadFile = File(...), user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        raw_filename = file.filename or "uploaded_document"
        filename = Path(raw_filename).name or "uploaded_document"
        suffix = os.path.splitext(filename)[1].lower()
        if not suffix or suffix not in SUPPORTED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"Unsupported file format '{suffix}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")
        allowed_mime = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", ".md": {"text/markdown", "text/plain"}, ".markdown": {"text/markdown", "text/plain"}, ".txt": {"text/plain", "text/markdown"}}
        declared = (file.content_type or "").lower()
        accepted = allowed_mime.get(suffix)
        if declared and ((isinstance(accepted, set) and declared not in accepted) or (isinstance(accepted, str) and declared != accepted)):
            raise HTTPException(status_code=415, detail=f"MIME type '{declared}' is not valid for '{suffix}'")

        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"Document exceeds maximum upload size of {MAX_UPLOAD_BYTES} bytes")
        if not content or not content.strip():
            raise HTTPException(status_code=400, detail="The uploaded document is empty")

        content_hash = hashlib.sha256(content).hexdigest()
        existing = artifacts.get_document_by_hash(project_id, content_hash)
        if existing:
            return JSONResponse(status_code=200, content=existing)

        document_id = "DOC-" + uuid.uuid4().hex[:12].upper()
        try:
            storage_path = filestore.save_file(project_id, document_id, filename, content)
            parsed_doc = parse_document(filename, content)
            sections, chunks = extract_sections_and_chunks(parsed_doc)

            sections_data = [
                {"section_id": s.section_id, "title": s.title, "level": s.level, "content": s.content, "chunk_count": s.chunk_count}
                for s in sections
            ]
            chunks_data = [
                {"chunk_id": f"{document_id}_{c.chunk_id}", "section_id": c.section_id, "section_title": c.section_title, "text": c.text, "kind": c.kind, "page": c.page}
                for c in chunks
            ]

            doc_record = artifacts.save_document(
                project_id=project_id,
                document_id=document_id,
                filename=filename,
                file_type=suffix,
                storage_path=storage_path,
                status="COMPLETED",
                section_count=len(sections),
                chunk_count=len(chunks),
                content_hash=content_hash,
            )
            artifacts.save_document_sections_and_chunks(document_id, project_id, sections_data, chunks_data)
            documents.add_chunks(document_id, project_id, chunks_data)
            artifacts.audit("DOCUMENT_UPLOADED", "project", project_id, actor_id=user_id, details={"document_id": document_id, "filename": filename})
            return doc_record
        except ValueError as exc:
            artifacts.save_document(project_id=project_id, document_id=document_id, filename=filename, file_type=suffix, storage_path="", status="FAILED", error_message=str(exc), content_hash=content_hash)
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            artifacts.save_document(project_id=project_id, document_id=document_id, filename=filename, file_type=suffix, storage_path="", status="FAILED", error_message=str(exc), content_hash=content_hash)
            raise HTTPException(status_code=422, detail=f"Document processing failed: {exc}") from exc

    @app.get("/projects/{project_id}/documents/{document_id}", tags=["Document Management"])
    async def get_project_document_status(project_id: str, document_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_document(project_id, document_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/documents/{document_id}/sections", tags=["Document Management"])
    async def get_project_document_sections(project_id: str, document_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.list_document_sections(project_id, document_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/workflows/requirements", status_code=202, tags=["Requirements Workflow (M1-M3)"])
    async def start_requirements_workflow(project_id: str, request: RequirementsWorkflowRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            brd_id = request.brd_id
            if not brd_id:
                target_doc_ids = request.document_ids
                if not target_doc_ids:
                    proj_docs = artifacts.list_documents(project_id)
                    target_doc_ids = [d["document_id"] for d in proj_docs if d.get("status") == "COMPLETED"]

                if not target_doc_ids:
                    raise HTTPException(status_code=400, detail="No document_ids provided and no completed documents found for project")

                combined_parts = []
                primary_filename = "project_documents.md"
                for doc_id in target_doc_ids:
                    doc_meta = artifacts.get_document(project_id, doc_id)
                    primary_filename = doc_meta.get("filename", primary_filename)
                    sections = artifacts.list_document_sections(project_id, doc_id)
                    if sections:
                        doc_text = "\n\n".join(s["content"] for s in sections if s.get("content"))
                    else:
                        chunks = artifacts.list_document_chunks(project_id, doc_id)
                        doc_text = "\n\n".join(c["text"] for c in chunks if c.get("text"))
                    if doc_text:
                        combined_parts.append(doc_text)

                combined_text = "\n\n---\n\n".join(combined_parts)
                if not combined_text.strip():
                    raise HTTPException(status_code=400, detail="Could not retrieve text content from specified document_ids")

                norm_doc = parse_document(primary_filename, combined_text.encode("utf-8"))
                extracted_model = ingestion.ingest(norm_doc)
                artifacts.save_requirements_model(extracted_model, combined_text, "text")
                brd_id = extracted_model.brd_id

            artifacts.get_requirements_model(brd_id)
            run = artifacts.create_workflow_run(project_id, brd_id)
            result = workflow.start(project_id, run["run_id"], brd_id)
            interrupted = bool(result.get("__interrupt__"))
            status = "PAUSED" if interrupted else result.get("status", "COMPLETED")
            artifacts.update_workflow_run(project_id, run["run_id"], status)
            artifacts.record_workflow_event(project_id, run["run_id"], "clarification_required" if interrupted else "workflow_completed", {"interrupted": interrupted})
            artifacts.audit("REQUIREMENTS_WORKFLOW_STARTED", "project", project_id, actor_id=user_id, details={"run_id": run["run_id"], "brd_id": brd_id})
            return JSONResponse(status_code=202, headers={"Location": f"/projects/{project_id}/runs/{run['run_id']}"}, content={**run, "status": status, "interrupt": interrupt_values(result)})
        except HTTPException:
            raise
        except PersistenceError as exc:
            code = 409 if "active workflow run" in str(exc) else 404
            raise HTTPException(status_code=code, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("requirements workflow failed")
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/runs/{run_id}")
    async def get_workflow_run(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_workflow_run(project_id, run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/runs/{run_id}/hitl/response")
    async def resume_workflow(project_id: str, run_id: str, request: WorkflowResumeRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            run = artifacts.get_workflow_run(project_id, run_id)
            result = workflow.resume(run_id, request.payload)
            interrupted = bool(result.get("__interrupt__"))
            status = "PAUSED" if interrupted else result.get("status", "COMPLETED")
            artifacts.update_workflow_run(project_id, run_id, status)
            artifacts.record_workflow_event(project_id, run_id, "approval_required" if interrupted and result.get("__interrupt__") and "approval_request" in str(result["__interrupt__"]) else "workflow_progress", {"interrupted": interrupted})
            artifacts.audit("WORKFLOW_HITL_RESUMED", "project", project_id, actor_id=user_id, details={"run_id": run_id, "status": status, "payload": request.payload})
            return {"run_id": run_id, "status": status, "interrupt": interrupt_values(result), "state": {k: v for k, v in result.items() if k != "__interrupt__"}}
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            artifacts.update_workflow_run(project_id, run_id, "FAILED", str(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/runs/{run_id}/approval")
    async def approval_response(project_id: str, run_id: str, request: WorkflowResumeRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        return await resume_workflow(project_id, run_id, request, user_id)

    @app.post("/projects/{project_id}/runs/{run_id}/clarifications")
    async def clarification_fallback(project_id: str, run_id: str, request: WorkflowResumeRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        payload = request.payload
        if isinstance(payload, dict) and payload.get("type") == "clarification_response":
            payload = [{"question_id": item.get("id"), "answer": item.get("answer", "")} for item in payload.get("answers", [])]
        return await resume_workflow(project_id, run_id, WorkflowResumeRequest(payload=payload), user_id)

    @app.post("/projects/{project_id}/runs/{run_id}/approve", tags=["Requirements Workflow (M1-M3)", "Planning Workflow (M4)"])
    async def approve_run(
        project_id: str,
        run_id: str,
        body: Optional[Dict[str, Any]] = Body(None),
        user_id: str = Depends(current_user)
    ) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        try:
            run = artifacts.get_planning_run(run_id, project_id=project_id)
            planning_wf.resume(run_id, {"decision": "APPROVE"})
            artifacts.update_planning_run(run_id, approval_status="APPROVED", status="APPROVED")
            return artifacts.get_planning_run(run_id, project_id=project_id)
        except PersistenceError:
            pass

        return await resume_workflow(project_id, run_id, WorkflowResumeRequest(payload={"decision": "APPROVE"}), user_id)

    @app.post("/projects/{project_id}/runs/{run_id}/reject", tags=["Requirements Workflow (M1-M3)", "Planning Workflow (M4)"])
    async def reject_run(
        project_id: str,
        run_id: str,
        body: Optional[Dict[str, Any]] = Body(None),
        user_id: str = Depends(current_user)
    ) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        feedback = body.get("feedback", "") if isinstance(body, dict) else ""
        if isinstance(body, dict) and "payload" in body and isinstance(body["payload"], dict):
            feedback = body["payload"].get("feedback", feedback)

        try:
            run = artifacts.get_planning_run(run_id, project_id=project_id)
            planning_wf.resume(run_id, {"decision": "REJECT", "feedback": feedback})
            artifacts.update_planning_run(run_id, approval_status="REJECTED", rejection_feedback=feedback, status="REVISION_REQUESTED")
            return artifacts.get_planning_run(run_id, project_id=project_id)
        except PersistenceError:
            pass

        return await resume_workflow(project_id, run_id, WorkflowResumeRequest(payload={"decision": "REJECT", "feedback": feedback}), user_id)

    @app.get("/projects/{project_id}/runs/{run_id}/events")
    async def workflow_events(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> StreamingResponse:
        try:
            artifacts.get_project(project_id, user_id)
            events = artifacts.list_workflow_events(project_id, run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        body = "".join(f"event: {item['event_type']}\ndata: {json.dumps(item)}\n\n" for item in events)
        return StreamingResponse(iter([body]), media_type="text/event-stream")

    @app.get("/projects/{project_id}/runs/{run_id}/artifacts", tags=["Requirements Workflow (M1-M3)", "Planning Workflow (M4)"])
    async def workflow_artifacts(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        artifacts.get_project(project_id, user_id)
        try:
            return artifacts.get_all_planning_artifacts(run_id, project_id=project_id)
        except PersistenceError:
            try:
                return artifacts.get_artifacts(project_id, run_id)
            except PersistenceError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc


    @app.get("/projects/{project_id}/runs")
    async def list_workflow_runs(project_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.list_workflow_runs(project_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/runs/{run_id}/cancel")
    async def cancel_workflow_run(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            run = artifacts.get_workflow_run(project_id, run_id)
            if run["status"] not in ("RUNNING", "PAUSED", "STARTING"):
                raise HTTPException(status_code=400, detail=f"Cannot cancel run with status '{run['status']}'")
            artifacts.update_workflow_run(project_id, run_id, "CANCELLED", "Run cancelled by user")
            artifacts.record_workflow_event(project_id, run_id, "workflow_cancelled", {"reason": "user_cancellation"})
            return {"run_id": run_id, "status": "CANCELLED", "message": "Workflow run cancelled successfully"}
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/requirements", response_model=RequirementsModel)
    async def get_project_requirements(project_id: str, user_id: str = Depends(current_user)) -> RequirementsModel:
        try:
            artifacts.get_project(project_id, user_id)
            runs = artifacts.list_workflow_runs(project_id)
            latest_brd_id = next((r["brd_id"] for r in runs if r.get("brd_id")), None)
            if not latest_brd_id:
                raise HTTPException(status_code=404, detail=f"No requirements model found for project '{project_id}'")
            model, _ = artifacts.get_requirements_model(latest_brd_id)
            return model
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/versions")
    async def get_project_versions(project_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            runs = artifacts.list_workflow_runs(project_id)
            latest_brd_id = next((r["brd_id"] for r in runs if r.get("brd_id")), None)
            if not latest_brd_id:
                return []
            return artifacts.list_brd_versions(latest_brd_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/audit")
    async def get_project_audit(project_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.list_audit(entity_id=project_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/workflows/{name}/graph.png", tags=["System & Infrastructure"])
    async def get_workflow_graph(name: str) -> Response:
        if name != "requirements":
            raise HTTPException(status_code=404, detail=f"Workflow '{name}' graph diagram not found")
        try:
            png_bytes = workflow.graph().get_graph().draw_mermaid_png()
            return Response(content=png_bytes, media_type="image/png")
        except Exception:
            mermaid_str = workflow.graph().get_graph().draw_mermaid()
            return Response(content=mermaid_str.encode("utf-8"), media_type="text/plain")

    @app.get("/health", response_model=HealthResponse, tags=["System & Infrastructure"])
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", milestone="BRD ingestion")

    @app.get("/healthz", tags=["System & Infrastructure"])
    async def healthz() -> Dict[str, Any]:
        checks: Dict[str, str] = {}
        try:
            with artifacts.connection() as db:
                db.execute("SELECT 1").fetchone()
            checks["sqlite"] = "ok"
        except Exception as exc:
            checks["sqlite"] = f"error: {exc}"
        try:
            documents._get_collection().count()
            checks["chromadb"] = "ok"
        except Exception as exc:
            checks["chromadb"] = f"error: {exc}"
        try:
            Path(os.getenv("DATA_ROOT", "data")).mkdir(parents=True, exist_ok=True)
            checks["filesystem"] = "ok"
        except Exception as exc:
            checks["filesystem"] = f"error: {exc}"
        healthy = all(value == "ok" for value in checks.values())
        return JSONResponse(status_code=200 if healthy else 503, content={"status": "ok" if healthy else "degraded", "checks": checks})


    @app.post("/api/requirements/analyze", response_model=RequirementsAnalysis, responses={400: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 422: {"model": ErrorResponse}}, tags=["Legacy Standalone APIs (Deprecated)"])
    async def analyze_requirements(request: AnalysisRequest) -> RequirementsAnalysis:
        try:
            extra = request.model_extra
            if request.brd_id and "source_filename" not in extra:
                requirements, model_version_id = artifacts.get_requirements_model(request.brd_id)
            else:
                requirements = RequirementsModel.model_validate(request.model_dump())
                model_version_id = artifacts.save_requirements_model(requirements, "", "model")
            logger.info("requirements analysis requested brd_id=%s", requirements.brd_id)
            analysis = requirements_analyzer.analyze(requirements)
            artifacts.audit("ANALYSIS_STARTED", "brd", requirements.brd_id)
            saved = artifacts.save_analysis(analysis, model_version_id)
            artifacts.update_latest_quality_status(requirements.brd_id, saved.quality_status, saved.status_reason)
            artifacts.audit("ANALYSIS_COMPLETED", "analysis", saved.analysis_id, details={"quality_status": saved.quality_status})
            return saved
        except PersistenceError as exc:
            logger.exception("persistence failed during requirements analysis")
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("requirements analysis failed brd_id=%s", requirements.brd_id)
            raise HTTPException(status_code=422, detail=f"Requirements Model could not be analyzed: {exc}") from exc

    @app.get("/api/brd/{brd_id}/requirements", response_model=RequirementsModel, responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}, tags=["Legacy Standalone APIs (Deprecated)"])
    async def get_requirements(brd_id: str) -> RequirementsModel:
        try:
            model, _ = artifacts.get_requirements_model(brd_id)
            return model
        except PersistenceError as exc:
            status = 404 if "no persisted" in str(exc) else 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/brd/{brd_id}/versions", tags=["Legacy Standalone APIs (Deprecated)"])
    async def get_brd_versions(brd_id: str) -> list[Dict[str, Any]]:
        try:
            return artifacts.list_brd_versions(brd_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/audit", tags=["Legacy Standalone APIs (Deprecated)"])
    async def get_audit(entity_type: Optional[str] = None, entity_id: Optional[str] = None) -> list[Dict[str, Any]]:
        return artifacts.list_audit(entity_type, entity_id)

    @app.get("/api/analysis/{analysis_id}", response_model=RequirementsAnalysis, responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}}, tags=["Legacy Standalone APIs (Deprecated)"])
    async def get_analysis(analysis_id: str) -> RequirementsAnalysis:
        try:
            return artifacts.get_analysis(analysis_id)
        except PersistenceError as exc:
            status = 404 if "no persisted" in str(exc) else 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/hitl/session", tags=["Legacy Standalone APIs (Deprecated)"])
    async def create_hitl_session(request: HITLSessionRequest) -> Dict[str, Any]:
        try:
            analysis = artifacts.get_analysis(request.analysis_id)
            if analysis.quality_status != "READY_FOR_CLARIFICATION" or not analysis.clarification_questions:
                raise HTTPException(status_code=409, detail="HITL is allowed only for READY_FOR_CLARIFICATION analyses with questions")
            return artifacts.create_hitl_session(request.analysis_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/hitl/session/{session_id}", tags=["Legacy Standalone APIs (Deprecated)"])
    async def get_hitl_session(session_id: str) -> Dict[str, Any]:
        try:
            return artifacts.get_hitl_session(session_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.websocket("/ws/hitl/{session_id}")
    async def hitl_websocket(websocket: WebSocket, session_id: str) -> None:
        await websocket.accept()
        try:
            state = artifacts.get_hitl_session(session_id)
            await websocket.send_json({"type": "resumed", "session_id": session_id, "status": state["status"]})
            while state["status"] != "COMPLETED":
                state = artifacts.get_hitl_session(session_id)
                answered = {item["question_id"] for item in state["answers"]}
                question = next((item for item in state["questions"] if item["question_id"] not in answered), None)
                if question is None:
                    break
                await websocket.send_json({"type": "question", "question": question})
                artifacts.audit("HITL_QUESTION_PRESENTED", "hitl_session", session_id, details={"question_id": question["question_id"]})
                message = await websocket.receive_json()
                if message.get("type") != "answer" or message.get("question_id") != question["question_id"]:
                    await websocket.send_json({"type": "error", "detail": "Expected an answer for the currently presented question."})
                    continue
                artifacts.audit("HITL_ANSWER_RECEIVED", "hitl_session", session_id, details={"question_id": question["question_id"]})
                state = artifacts.record_answer(session_id, question["question_id"], str(message.get("answer", "")))
                await websocket.send_json({"type": "answer_acknowledged", "question_id": question["question_id"]})
                if state["status"] == "COMPLETED":
                    analysis = artifacts.get_analysis(state["analysis_id"])
                    requirements, _ = artifacts.get_requirements_model(state["brd_id"])
                    round_number = int(state.get("follow_up_round", 0)) + 1
                    question_map = {item["question_id"]: item for item in state["questions"]}
                    answers = [dict(item, question=question_map.get(item["question_id"], {}).get("question", ""), issue_id=question_map.get(item["question_id"], {}).get("issue_id")) for item in state["answers"]]
                    if int(state.get("follow_up_round", 0)) > 0:
                        prefix = f"Q-{int(state['follow_up_round']):01d}"
                        answers = [item for item in answers if item["question_id"].startswith(prefix)]
                    flags = requirements_analyzer._answer_quality_flags(answers)
                    max_rounds = int(os.getenv("MAX_FOLLOW_UP_ROUNDS", "2"))
                    if flags and round_number > max_rounds:
                        decisions = requirements_analyzer.generate_best_decisions(requirements, analysis, answers)
                        artifacts.save_best_decisions(session_id, decisions)
                        artifacts.create_resolved_model(session_id)
                        artifacts.audit("HITL_SESSION_COMPLETED", "hitl_session", session_id, details={"best_decisions": len(decisions), "follow_up_limit_reached": True})
                        await websocket.send_json({"type": "best_decisions", "decisions": decisions, "follow_up_limit_reached": True})
                        await websocket.send_json({"type": "completed", "session_id": session_id})
                        break
                    follow_ups = requirements_analyzer.generate_follow_up_questions(requirements, analysis, answers, round_number) if flags else []
                    if follow_ups and round_number <= max_rounds:
                        state = artifacts.add_follow_up_questions(session_id, follow_ups, round_number)
                        continue
                    artifacts.create_resolved_model(session_id)
                    artifacts.audit("HITL_SESSION_COMPLETED", "hitl_session", session_id)
            await websocket.send_json({"type": "completed", "session_id": session_id})
        except WebSocketDisconnect:
            try:
                artifacts.audit("HITL_SESSION_RESUMED", "hitl_session", session_id, result="DISCONNECTED")
            except Exception:
                logger.exception("failed to audit HITL disconnect")
        except Exception as exc:
            logger.exception("HITL websocket failed")
            await websocket.send_json({"type": "error", "detail": str(exc)})
            try:
                artifacts.audit("HITL_SESSION_FAILED", "hitl_session", session_id, result="FAILED", details={"reason": str(exc)})
            except Exception:
                logger.exception("failed to audit HITL failure")

    @app.websocket("/projects/{project_id}/runs/{run_id}/hitl")
    async def project_run_hitl(websocket: WebSocket, project_id: str, run_id: str) -> None:
        try:
            token = websocket.query_params.get("access_token")
            if not token:
                authorization = websocket.headers.get("authorization", "")
                token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else ""
            user_id = decode_token(token)
            artifacts.get_project(project_id, user_id)
            await websocket.accept()

            pending = planning_wf.pending_interrupt(run_id) or workflow.pending_interrupt(run_id)
            if pending:
                await websocket.send_json(pending)
            while True:
                message = await websocket.receive_json()
                message_type = message.get("type")
                if message_type == "clarification_response":
                    payload = [{"question_id": item.get("id"), "answer": item.get("answer", "")} for item in message.get("answers", [])]
                elif message_type == "approval_response":
                    payload = {"decision": message.get("decision", ""), "feedback": message.get("feedback", "")}
                else:
                    await websocket.send_json({"type": "error", "code": "invalid_message", "message": "Expected clarification_response or approval_response"})
                    continue

                is_planning = True
                try:
                    artifacts.get_planning_run(run_id, project_id=project_id)
                except Exception:
                    is_planning = False

                if is_planning:
                    result = planning_wf.resume(run_id, payload)
                else:
                    result = workflow.resume(run_id, payload)

                interrupted = bool(result.get("__interrupt__"))
                status = "PAUSED" if interrupted else result.get("status", "COMPLETED")
                artifacts.audit("WORKFLOW_HITL_WEBSOCKET_MESSAGE", "project", project_id, actor_id=user_id, details={"run_id": run_id, "type": message_type, "payload": payload})
                if interrupted:
                    next_pending = planning_wf.pending_interrupt(run_id) or workflow.pending_interrupt(run_id)
                    await websocket.send_json(next_pending or interrupt_values(result)[0])
                else:
                    await websocket.send_json({"type": "completed", "run_id": run_id, "status": status})
                    break
        except WebSocketDisconnect:
            return
        except Exception as exc:
            try:
                await websocket.close(code=1008, reason=str(exc))
            except Exception:
                return

    # Milestone 4: Planning Workflow Routes

    @app.post("/projects/{project_id}/workflows/planning", status_code=202, tags=["Planning Workflow (M4)"])
    async def start_planning_workflow(
        project_id: str,
        request: PlanningWorkflowRequest = Body(default_factory=PlanningWorkflowRequest),
        response: Response = None,
        user_id: str = Depends(current_user)
    ) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        model: Optional[RequirementsModel] = None
        version_id: Optional[int] = None

        # Input precedence 1: requirements_model_version_id
        if request.requirements_model_version_id is not None:
            try:
                with artifacts.connection() as db:
                    row = db.execute("SELECT model_json, model_version_id FROM requirements_models WHERE model_version_id=?", (request.requirements_model_version_id,)).fetchone()
                    if not row:
                        raise HTTPException(status_code=404, detail=f"Requirements Model version {request.requirements_model_version_id} not found")
                    model = RequirementsModel.model_validate_json(row["model_json"])
                    version_id = int(row["model_version_id"])
            except Exception as exc:
                if isinstance(exc, HTTPException):
                    raise exc
                raise HTTPException(status_code=404, detail=f"Requirements Model version {request.requirements_model_version_id} not found") from exc

        # Input precedence 2: document_ids supplied
        if model is None and request.document_ids:
            seen_docs = set()
            clean_doc_ids = []
            for d in request.document_ids:
                if d not in seen_docs:
                    seen_docs.add(d)
                    clean_doc_ids.append(d)

            for doc_id in clean_doc_ids:
                doc = None
                try:
                    doc = artifacts.get_document(project_id, doc_id)
                except PersistenceError as exc:
                    with artifacts.connection() as db:
                        row = db.execute("SELECT project_id FROM documents WHERE document_id=?", (doc_id,)).fetchone()
                        if row:
                            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' does not belong to project '{project_id}'")
                        else:
                            raise HTTPException(status_code=404, detail=f"Document '{doc_id}' not found") from exc

                if doc["status"] != "COMPLETED":
                    raise HTTPException(status_code=400, detail=f"Document '{doc_id}' is not in COMPLETED status (status={doc['status']})")

            all_chunks = []
            for doc_id in clean_doc_ids:
                chunks = artifacts.list_document_chunks(project_id, doc_id)
                all_chunks.extend(chunks)

            if not all_chunks:
                raise HTTPException(status_code=400, detail="No document chunks found for the provided document_ids")

            reconstructed_text = "\n\n".join(chunk.get("text", "") for chunk in all_chunks)
            doc_hashes = [doc_id for doc_id in clean_doc_ids]

            try:
                extracted_model = ingestion.extract_requirements_model(
                    content=reconstructed_text,
                    file_type="markdown",
                    source_filename=f"project-{project_id}-combined.md"
                )
                brd_id = f"BRD-{uuid.uuid4().hex[:8].upper()}"
                extracted_model = extracted_model.model_copy(update={
                    "brd_id": brd_id,
                    "extraction_metadata": {
                        "source_document_ids": clean_doc_ids,
                        "content_hashes": doc_hashes,
                        "project_id": project_id
                    }
                })
                version_id = artifacts.save_requirements_model(extracted_model, reconstructed_text, "markdown")
                model = extracted_model
            except Exception as exc:
                if isinstance(exc, HTTPException):
                    raise exc
                raise HTTPException(status_code=400, detail=f"Requirements extraction from documents failed: {exc}") from exc

        # Input precedence 3: brd_id compatibility path
        if model is None and request.brd_id:
            try:
                model, version_id = artifacts.get_requirements_model(request.brd_id)
            except PersistenceError as exc:
                raise HTTPException(status_code=404, detail=f"BRD '{request.brd_id}' not found") from exc

        # Input precedence 4: latest resolved model for project
        if model is None:
            try:
                with artifacts.connection() as db:
                    row = db.execute(
                        "SELECT rm.model_json, rm.model_version_id FROM requirements_models rm "
                        "JOIN brds b ON rm.brd_id = b.brd_id "
                        "WHERE b.brd_id LIKE ? OR b.source_filename LIKE ? ORDER BY rm.version DESC LIMIT 1",
                        (f"%{project_id}%", f"%{project_id}%")
                    ).fetchone()
                    if row:
                        model = RequirementsModel.model_validate_json(row["model_json"])
                        version_id = int(row["model_version_id"])
            except Exception:
                pass


        if model is None:
            raise HTTPException(status_code=400, detail="No valid requirements model, document_ids, or brd_id provided to start planning workflow")

        run_id = f"RUN-{uuid.uuid4().hex[:12].upper()}"
        res = planning_wf.start(
            project_id=project_id,
            run_id=run_id,
            requirements_model=model,
            source_model_version_id=version_id,
            source_document_ids=request.document_ids or []
        )

        if response:
            response.headers["Location"] = f"/projects/{project_id}/runs/{run_id}"

        run_data = artifacts.get_planning_run(run_id, project_id=project_id)
        pending = planning_wf.pending_interrupt(run_id)
        return {
            "run_id": run_id,
            "project_id": project_id,
            "status": run_data.get("status", "RUNNING"),
            "current_stage": run_data.get("current_stage", "INITIALIZING"),
            "planning_route": run_data.get("planning_route", "simple"),
            "source_model_version_id": version_id,
            "approval_status": run_data.get("approval_status", "PENDING"),
            "interrupt": pending
        }

    @app.get("/projects/{project_id}/runs/{run_id}/tasks", tags=["Planning Workflow (M4)"])
    async def get_planning_tasks(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_planning_tasks(run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.patch("/projects/{project_id}/runs/{run_id}/tasks/{task_id}", tags=["Planning Workflow (M4)"])
    async def patch_planning_task(
        project_id: str,
        run_id: str,
        task_id: str,
        request: TaskPatchRequest,
        user_id: str = Depends(current_user)
    ) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            run = artifacts.get_planning_run(run_id, project_id=project_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        if run.get("approval_status") == "APPROVED" or run.get("status") in ["APPROVED", "COMPLETED"]:
            raise HTTPException(status_code=400, detail="Cannot edit planning tasks after plan has been approved")

        if request.split_into:
            tasks = artifacts.split_planning_task(run_id, task_id, [s.model_dump(mode="json") for s in request.split_into])
        else:
            updates = {}
            if request.title is not None:
                updates["title"] = request.title
            if request.description is not None:
                updates["description"] = request.description
            if request.sequence_number is not None:
                updates["sequence_number"] = request.sequence_number
            if request.target_files is not None:
                updates["target_files"] = request.target_files
            if request.acceptance_criteria is not None:
                updates["acceptance_criteria"] = request.acceptance_criteria
            if request.dependency_task_ids is not None:
                updates["dependency_task_ids"] = request.dependency_task_ids
            artifacts.update_planning_task(run_id, task_id, updates)
            tasks = artifacts.get_planning_tasks(run_id)

        seq_map = {t["task_id"]: t["sequence_number"] for t in tasks}
        for t in tasks:
            tid = t["task_id"]
            seq = t["sequence_number"]
            for dep in t.get("dependency_task_ids", []):
                if dep not in seq_map:
                    raise HTTPException(status_code=400, detail=f"Task '{tid}' references missing dependency '{dep}'")
                if seq_map[dep] >= seq:
                    raise HTTPException(status_code=400, detail=f"Task '{tid}' has invalid forward or cyclic dependency on '{dep}'")

        return tasks



    @app.get("/projects/{project_id}/runs/{run_id}/patterns", tags=["Planning Workflow (M4)"])
    async def get_run_patterns(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_selected_patterns(run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/runs/{run_id}/research", tags=["Planning Workflow (M4)"])
    async def get_run_research(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_research_findings(run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/runs/{run_id}/architecture", tags=["Planning Workflow (M4)"])
    async def get_run_architecture(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_architecture_document(run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc




    # Pattern Knowledge Base Endpoints

    @app.post("/patterns", status_code=201, response_model=PatternModel, tags=["Pattern Knowledge Base"])
    async def create_pattern(request: PatternCreateRequest, user_id: str = Depends(current_user)) -> PatternModel:
        try:
            return patterns_svc.create_pattern(request)
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/patterns/bulk", status_code=201, response_model=List[PatternModel], tags=["Pattern Knowledge Base"])
    async def bulk_create_patterns(
        request: Request,
        body: Optional[List[PatternCreateRequest]] = Body(None, description="List of pattern objects for bulk creation"),
        user_id: str = Depends(current_user)
    ) -> List[PatternModel]:
        try:
            if body is not None:
                return patterns_svc.bulk_create_patterns(body)
            content_type = (request.headers.get("content-type") or "").lower()
            if "multipart/form-data" in content_type:
                form = await request.form()
                upload = form.get("file")
                if upload is None:
                    raise HTTPException(status_code=422, detail="multipart bulk upload requires a file field")
                import yaml
                raw = yaml.safe_load(await upload.read())
            elif "yaml" in content_type or "yml" in content_type:
                import yaml
                raw = yaml.safe_load(await request.body())
            else:
                raw = await request.json()
            items = [PatternCreateRequest.model_validate(item) for item in (raw.get("patterns", raw) if isinstance(raw, dict) else raw)]
            return patterns_svc.bulk_create_patterns(items)
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.post("/patterns/search", response_model=List[PatternSearchResult], tags=["Pattern Knowledge Base"])
    async def search_patterns(request: PatternSearchRequest, user_id: str = Depends(current_user)) -> List[PatternSearchResult]:
        try:
            return patterns_svc.search_patterns(request)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/patterns", response_model=List[PatternModel], tags=["Pattern Knowledge Base"])
    async def list_patterns(tag: Optional[str] = None, user_id: str = Depends(current_user)) -> List[PatternModel]:
        return patterns_svc.list_patterns(tag=tag)

    @app.get("/patterns/{pattern_id}", response_model=PatternModel, tags=["Pattern Knowledge Base"])
    async def get_pattern(pattern_id: str, user_id: str = Depends(current_user)) -> PatternModel:
        try:
            return patterns_svc.get_pattern(pattern_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found") from exc

    @app.patch("/patterns/{pattern_id}", response_model=PatternModel, tags=["Pattern Knowledge Base"])
    async def update_pattern(pattern_id: str, request: PatternUpdateRequest, user_id: str = Depends(current_user)) -> PatternModel:
        try:
            return patterns_svc.update_pattern(pattern_id, request)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found") from exc
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/patterns/{pattern_id}", response_model=PatternModel, tags=["Pattern Knowledge Base"])
    async def delete_pattern(pattern_id: str, user_id: str = Depends(current_user)) -> PatternModel:
        try:
            return patterns_svc.delete_pattern(pattern_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=f"Pattern '{pattern_id}' not found") from exc

    @app.exception_handler(HTTPException)
    async def http_error_handler(_, exc: HTTPException) -> JSONResponse:
        message = str(exc.detail)
        return JSONResponse(status_code=exc.status_code, content={"error": "brd_ingestion_failed", "detail": message, "details": {"code": f"http_{exc.status_code}", "message": message}})

    return app


app = create_app()
