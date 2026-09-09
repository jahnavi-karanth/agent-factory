from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .llm import ExtractionError
from .analysis_models import RequirementsAnalysis
from .analyzer import RequirementsAnalyzer
from .models import ErrorResponse, HealthResponse, RequirementsModel
from .parser import parse_document
from .service import IngestionService

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger(__name__)

MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))


def create_app(service: Optional[IngestionService] = None, analyzer: Optional[RequirementsAnalyzer] = None) -> FastAPI:
    app = FastAPI(title="AI Software Development Factory", version="0.1.0", description="Milestone 1: generic BRD ingestion")
    ingestion = service or IngestionService()
    requirements_analyzer = analyzer or RequirementsAnalyzer()

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
            return ingestion.ingest(document)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("workflow failed filename=%s", filename)
            raise HTTPException(status_code=422, detail=f"BRD could not be converted into a valid Requirements Model: {exc}") from exc

    @app.post("/api/requirements/analyze", response_model=RequirementsAnalysis, responses={400: {"model": ErrorResponse}, 502: {"model": ErrorResponse}, 422: {"model": ErrorResponse}})
    async def analyze_requirements(requirements: RequirementsModel) -> RequirementsAnalysis:
        logger.info("requirements analysis requested brd_id=%s", requirements.brd_id)
        try:
            return requirements_analyzer.analyze(requirements)
        except ExtractionError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("requirements analysis failed brd_id=%s", requirements.brd_id)
            raise HTTPException(status_code=422, detail=f"Requirements Model could not be analyzed: {exc}") from exc

    @app.exception_handler(HTTPException)
    async def http_error_handler(_, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": "brd_ingestion_failed", "detail": str(exc.detail)})

    return app


app = create_app()
