from __future__ import annotations

import logging
import os
import json
import uuid
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from .llm import ExtractionError
from .analysis_models import RequirementsAnalysis
from .analyzer import RequirementsAnalyzer
from .models import ErrorResponse, HealthResponse, RequirementsModel
from .parser import parse_document
from .repository import PersistenceError, SQLiteRepository
from .service import IngestionService
from .workflow import RequirementsWorkflow
from .document_store import DocumentStore
from .auth import create_token, current_user, decode_token, hash_password, verify_password

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    brd_id: Optional[str] = None


class HITLSessionRequest(BaseModel):
    analysis_id: str


class ProjectRequest(BaseModel):
    name: str
    owner_id: Optional[str] = None


class RequirementsWorkflowRequest(BaseModel):
    brd_id: str


class WorkflowResumeRequest(BaseModel):
    payload: Any


class AuthRequest(BaseModel):
    email: str
    password: str


def create_app(service: Optional[IngestionService] = None, analyzer: Optional[RequirementsAnalyzer] = None, repository: Optional[SQLiteRepository] = None, document_store: Optional[DocumentStore] = None) -> FastAPI:
    app = FastAPI(title="AI Software Development Factory", version="0.1.0", description="Milestone 1: generic BRD ingestion")
    ingestion = service or IngestionService()
    requirements_analyzer = analyzer or RequirementsAnalyzer()
    artifacts = repository or SQLiteRepository()
    workflow = RequirementsWorkflow(artifacts, requirements_analyzer)
    documents = document_store or DocumentStore()

    @app.post("/auth/register", status_code=201)
    async def register(request: AuthRequest) -> Dict[str, Any]:
        user_id = "USR-" + uuid.uuid4().hex[:12].upper()
        try:
            user = artifacts.create_user(user_id, request.email, hash_password(request.password))
            return {**user, "access_token": create_token(user_id), "token_type": "bearer"}
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/auth/token")
    async def login(request: AuthRequest) -> Dict[str, Any]:
        try:
            user = artifacts.get_user_by_email(request.email)
            if not verify_password(request.password, user["password_hash"]):
                raise HTTPException(status_code=401, detail="invalid credentials")
            return {"access_token": create_token(user["user_id"]), "token_type": "bearer"}
        except PersistenceError as exc:
            raise HTTPException(status_code=401, detail="invalid credentials") from exc

    @app.post("/projects", status_code=201)
    async def create_project(request: ProjectRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        project_id = "PROJ-" + uuid.uuid4().hex[:12].upper()
        try:
            return artifacts.create_project(project_id, request.name, user_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/workflows/requirements", status_code=202)
    async def start_requirements_workflow(project_id: str, request: RequirementsWorkflowRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            artifacts.get_requirements_model(request.brd_id)
            run = artifacts.create_workflow_run(project_id, request.brd_id)
            result = workflow.start(project_id, run["run_id"], request.brd_id)
            interrupted = bool(result.get("__interrupt__"))
            status = "PAUSED" if interrupted else result.get("status", "COMPLETED")
            artifacts.update_workflow_run(project_id, run["run_id"], status)
            artifacts.record_workflow_event(project_id, run["run_id"], "clarification_required" if interrupted else "workflow_completed", {"interrupted": interrupted})
            return {**run, "status": status, "interrupt": result.get("__interrupt__", [])}
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
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
            return {"run_id": run_id, "status": status, "interrupt": result.get("__interrupt__", []), "state": result}
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            artifacts.update_workflow_run(project_id, run_id, "FAILED", str(exc))
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/projects/{project_id}/runs/{run_id}/approval")
    async def approval_response(project_id: str, run_id: str, request: WorkflowResumeRequest, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        return await resume_workflow(project_id, run_id, request, user_id)

    @app.get("/projects/{project_id}/runs/{run_id}/events")
    async def workflow_events(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> StreamingResponse:
        try:
            artifacts.get_project(project_id, user_id)
            events = artifacts.list_workflow_events(project_id, run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        body = "".join(f"event: {item['event_type']}\ndata: {json.dumps(item)}\n\n" for item in events)
        return StreamingResponse(iter([body]), media_type="text/event-stream")

    @app.get("/projects/{project_id}/runs/{run_id}/artifacts")
    async def workflow_artifacts(project_id: str, run_id: str, user_id: str = Depends(current_user)) -> Dict[str, Any]:
        try:
            artifacts.get_project(project_id, user_id)
            return artifacts.get_artifacts(project_id, run_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/projects/{project_id}/documents/search")
    async def search_project_documents(project_id: str, q: str, limit: int = 5, user_id: str = Depends(current_user)) -> list[Dict[str, Any]]:
        try:
            artifacts.get_project(project_id, user_id)
            return documents.search(project_id, q, max(1, min(limit, 20)))
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", milestone="BRD ingestion")

    @app.post("/api/brd/upload", response_model=RequirementsModel, responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
    async def upload_brd(file: UploadFile = File(...), project_id: Optional[str] = None) -> RequirementsModel:
        filename = file.filename or "uploaded_brd"
        logger.info("upload received filename=%s", filename)
        content = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail=f"BRD exceeds maximum upload size of {MAX_UPLOAD_BYTES} bytes")
        try:
            logger.info("document parsing started filename=%s", filename)
            document = parse_document(filename, content)
            logger.info("document parsing completed filename=%s", filename)
            model = ingestion.ingest(document)
            if project_id:
                artifacts.get_project(project_id)
            artifacts.save_requirements_model(model, document.text, os.path.splitext(filename)[1].lower() or "text")
            if project_id:
                documents.add(model.brd_id, project_id, filename, document.text, {"source_filename": filename})
            artifacts.audit("BRD_UPLOADED", "brd", model.brd_id, details={"filename": filename})
            artifacts.audit("REQUIREMENTS_MODEL_CREATED", "requirements_model", model.brd_id, details={"requirement_count": len(model.requirements)})
            return model
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("workflow failed filename=%s", filename)
            raise HTTPException(status_code=422, detail=f"BRD could not be converted into a valid Requirements Model: {exc}") from exc

    @app.post("/api/requirements/analyze", response_model=RequirementsAnalysis, responses={400: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
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

    @app.get("/api/brd/{brd_id}/requirements", response_model=RequirementsModel, responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    async def get_requirements(brd_id: str) -> RequirementsModel:
        try:
            model, _ = artifacts.get_requirements_model(brd_id)
            return model
        except PersistenceError as exc:
            status = 404 if "no persisted" in str(exc) else 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.get("/api/brd/{brd_id}/versions")
    async def get_brd_versions(brd_id: str) -> list[Dict[str, Any]]:
        try:
            return artifacts.list_brd_versions(brd_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/audit")
    async def get_audit(entity_type: Optional[str] = None, entity_id: Optional[str] = None) -> list[Dict[str, Any]]:
        return artifacts.list_audit(entity_type, entity_id)

    @app.get("/api/analysis/{analysis_id}", response_model=RequirementsAnalysis, responses={404: {"model": ErrorResponse}, 503: {"model": ErrorResponse}})
    async def get_analysis(analysis_id: str) -> RequirementsAnalysis:
        try:
            return artifacts.get_analysis(analysis_id)
        except PersistenceError as exc:
            status = 404 if "no persisted" in str(exc) else 503
            raise HTTPException(status_code=status, detail=str(exc)) from exc

    @app.post("/api/hitl/session")
    async def create_hitl_session(request: HITLSessionRequest) -> Dict[str, Any]:
        try:
            analysis = artifacts.get_analysis(request.analysis_id)
            if analysis.quality_status != "READY_FOR_CLARIFICATION" or not analysis.clarification_questions:
                raise HTTPException(status_code=409, detail="HITL is allowed only for READY_FOR_CLARIFICATION analyses with questions")
            return artifacts.create_hitl_session(request.analysis_id)
        except PersistenceError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/hitl/session/{session_id}")
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
        await websocket.accept()
        try:
            token = websocket.query_params.get("access_token")
            if not token:
                authorization = websocket.headers.get("authorization", "")
                token = authorization.split(" ", 1)[1] if authorization.lower().startswith("bearer ") else ""
            user_id = decode_token(token)
            artifacts.get_project(project_id, user_id)
            artifacts.get_workflow_run(project_id, run_id)
            await websocket.send_json({"type": "resumed", "project_id": project_id, "run_id": run_id})
            message = await websocket.receive_json()
            result = workflow.resume(run_id, message.get("payload", message))
            interrupted = bool(result.get("__interrupt__"))
            artifacts.update_workflow_run(project_id, run_id, "PAUSED" if interrupted else result.get("status", "COMPLETED"))
            await websocket.send_json({"type": "approval_request" if interrupted and "approval_request" in str(result.get("__interrupt__")) else "clarification_request" if interrupted else "completed", "run_id": run_id, "interrupt": result.get("__interrupt__", []), "state": result})
        except WebSocketDisconnect:
            return
        except Exception as exc:
            await websocket.send_json({"type": "error", "detail": str(exc)})

    @app.exception_handler(HTTPException)
    async def http_error_handler(_, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": "brd_ingestion_failed", "detail": str(exc.detail)})

    return app


app = create_app()
