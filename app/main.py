from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from .llm import ExtractionError
from .analysis_models import RequirementsAnalysis
from .analyzer import RequirementsAnalyzer
from .models import ErrorResponse, HealthResponse, RequirementsModel
from .parser import parse_document
from .repository import PersistenceError, SQLiteRepository
from .service import IngestionService

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    brd_id: Optional[str] = None


class HITLSessionRequest(BaseModel):
    analysis_id: str


def create_app(service: Optional[IngestionService] = None, analyzer: Optional[RequirementsAnalyzer] = None, repository: Optional[SQLiteRepository] = None) -> FastAPI:
    app = FastAPI(title="AI Software Development Factory", version="0.1.0", description="Milestone 1: generic BRD ingestion")
    ingestion = service or IngestionService()
    requirements_analyzer = analyzer or RequirementsAnalyzer()
    artifacts = repository or SQLiteRepository()

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", milestone="BRD ingestion")

    @app.post("/api/brd/upload", response_model=RequirementsModel, responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}, 422: {"model": ErrorResponse}, 502: {"model": ErrorResponse}})
    async def upload_brd(file: UploadFile = File(...)) -> RequirementsModel:
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
            artifacts.save_requirements_model(model, document.text, os.path.splitext(filename)[1].lower() or "text")
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

    @app.exception_handler(HTTPException)
    async def http_error_handler(_, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": "brd_ingestion_failed", "detail": str(exc.detail)})

    return app


app = create_app()
