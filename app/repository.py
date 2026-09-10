from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

from .analysis_models import RequirementsAnalysis
from .models import RequirementsModel


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistenceError(RuntimeError):
    """Raised when a persistence operation cannot be completed."""


class SQLiteRepository:
    def __init__(self, path: Optional[str] = None):
        self.path = path or os.getenv("DATABASE_PATH", str(Path("data") / "agent_factory.sqlite3"))
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self.initialize()
        except sqlite3.Error as exc:
            raise PersistenceError(f"database initialization failed: {exc}") from exc

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connection() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS brds (
                    brd_id TEXT PRIMARY KEY,
                    title TEXT,
                    source_filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    original_content TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS brd_versions (
                    version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brd_id TEXT NOT NULL REFERENCES brds(brd_id),
                    version INTEGER NOT NULL,
                    parent_version_id INTEGER REFERENCES brd_versions(version_id),
                    quality_status TEXT NOT NULL DEFAULT 'READY',
                    status_reason TEXT,
                    created_at TEXT NOT NULL,
                    UNIQUE(brd_id, version)
                );
                CREATE TABLE IF NOT EXISTS requirements_models (
                    model_version_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    brd_id TEXT NOT NULL REFERENCES brds(brd_id),
                    version INTEGER NOT NULL,
                    model_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(brd_id, version)
                );
                CREATE TABLE IF NOT EXISTS requirements (
                    model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id) ON DELETE CASCADE,
                    requirement_id TEXT NOT NULL,
                    type TEXT NOT NULL,
                    description TEXT NOT NULL,
                    source_json TEXT NOT NULL,
                    priority TEXT,
                    PRIMARY KEY(model_version_id, requirement_id),
                    UNIQUE(model_version_id, requirement_id)
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    analysis_id TEXT PRIMARY KEY,
                    brd_id TEXT NOT NULL REFERENCES brds(brd_id),
                    model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    status TEXT NOT NULL,
                    summary_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS issues (
                    issue_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    severity_reason TEXT NOT NULL,
                    clarification_required INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(analysis_id, issue_id)
                );
                CREATE TABLE IF NOT EXISTS issue_requirements (
                    analysis_id TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    model_version_id INTEGER NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(analysis_id, issue_id, requirement_id),
                    FOREIGN KEY(analysis_id, issue_id) REFERENCES issues(analysis_id, issue_id) ON DELETE CASCADE,
                    FOREIGN KEY(model_version_id, requirement_id) REFERENCES requirements(model_version_id, requirement_id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TABLE IF NOT EXISTS clarification_questions (
                    question_id TEXT NOT NULL,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id) ON DELETE CASCADE,
                    issue_id TEXT NOT NULL,
                    model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    question TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(analysis_id, question_id),
                    FOREIGN KEY(analysis_id, issue_id) REFERENCES issues(analysis_id, issue_id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS question_requirements (
                    analysis_id TEXT NOT NULL,
                    question_id TEXT NOT NULL,
                    model_version_id INTEGER NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(analysis_id, question_id, requirement_id),
                    FOREIGN KEY(analysis_id, question_id) REFERENCES clarification_questions(analysis_id, question_id) ON DELETE CASCADE,
                    FOREIGN KEY(model_version_id, requirement_id) REFERENCES requirements(model_version_id, requirement_id) DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TABLE IF NOT EXISTS audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    actor_type TEXT NOT NULL,
                    actor_id TEXT,
                    action TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    result TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    request_id TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_logs(entity_type, entity_id, timestamp);
                CREATE TABLE IF NOT EXISTS hitl_sessions (
                    session_id TEXT PRIMARY KEY,
                    analysis_id TEXT NOT NULL REFERENCES analyses(analysis_id),
                    brd_id TEXT NOT NULL REFERENCES brds(brd_id),
                    status TEXT NOT NULL,
                    current_question_id TEXT,
                    follow_up_round INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS hitl_answers (
                    answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES hitl_sessions(session_id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(session_id, question_id)
                );
                CREATE TABLE IF NOT EXISTS resolved_requirements_models (
                    resolved_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES hitl_sessions(session_id),
                    model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    source_model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hitl_analysis ON hitl_sessions(analysis_id);
                CREATE INDEX IF NOT EXISTS idx_models_brd ON requirements_models(brd_id, version);
                CREATE INDEX IF NOT EXISTS idx_requirements_id ON requirements(requirement_id);
                CREATE INDEX IF NOT EXISTS idx_analyses_brd ON analyses(brd_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_issues_analysis ON issues(analysis_id);
                CREATE INDEX IF NOT EXISTS idx_questions_analysis ON clarification_questions(analysis_id);
                """
            )

    def save_requirements_model(self, model: RequirementsModel, content: str, file_type: str) -> int:
        now = utc_now()
        model_json = model.model_dump_json()
        try:
            with self.connection() as db:
                db.execute("BEGIN")
                db.execute(
                    "INSERT INTO brds(brd_id,title,source_filename,file_type,original_content,created_at,updated_at) VALUES(?,?,?,?,?,?,?) "
                    "ON CONFLICT(brd_id) DO UPDATE SET title=excluded.title,source_filename=excluded.source_filename,file_type=excluded.file_type,original_content=excluded.original_content,updated_at=excluded.updated_at",
                    (model.brd_id, model.title, model.source_filename, file_type, content, now, now),
                )
                row = db.execute("SELECT COALESCE(MAX(version), 0) + 1 AS next_version FROM requirements_models WHERE brd_id=?", (model.brd_id,)).fetchone()
                version = int(row["next_version"])
                cursor = db.execute("INSERT INTO requirements_models(brd_id,version,model_json,created_at) VALUES(?,?,?,?)", (model.brd_id, version, model_json, now))
                model_version_id = int(cursor.lastrowid)
                previous = db.execute("SELECT version_id FROM brd_versions WHERE brd_id=? ORDER BY version DESC LIMIT 1", (model.brd_id,)).fetchone()
                db.execute("INSERT INTO brd_versions(brd_id,version,parent_version_id,quality_status,created_at) VALUES(?,?,?,?,?)", (model.brd_id, version, previous["version_id"] if previous else None, "READY", now))
                for requirement in model.requirements:
                    db.execute(
                        "INSERT INTO requirements(model_version_id,requirement_id,type,description,source_json,priority) VALUES(?,?,?,?,?,?)",
                        (model_version_id, requirement.id, requirement.type, requirement.description, json.dumps(requirement.source.model_dump()), requirement.priority),
                    )
                db.commit()
                return model_version_id
        except sqlite3.Error as exc:
            raise PersistenceError(f"requirements persistence failed: {exc}") from exc

    def get_requirements_model(self, brd_id: str) -> Tuple[RequirementsModel, int]:
        try:
            with self.connection() as db:
                row = db.execute("SELECT model_json, model_version_id FROM requirements_models WHERE brd_id=? ORDER BY version DESC LIMIT 1", (brd_id,)).fetchone()
                if not row:
                    raise PersistenceError(f"no persisted Requirements Model found for brd_id {brd_id}")
                return RequirementsModel.model_validate_json(row["model_json"]), int(row["model_version_id"])
        except sqlite3.Error as exc:
            raise PersistenceError(f"requirements retrieval failed: {exc}") from exc

    def save_analysis(self, analysis: RequirementsAnalysis, model_version_id: int) -> RequirementsAnalysis:
        now = utc_now()
        analysis_id = analysis.analysis_id
        try:
            with self.connection() as db:
                db.execute("BEGIN")
                if db.execute("SELECT 1 FROM analyses WHERE analysis_id=?", (analysis_id,)).fetchone():
                    suffix = hashlib.sha256(f"{analysis_id}:{now}".encode()).hexdigest()[:12].upper()
                    analysis_id = f"ANALYSIS-{suffix}"
                    analysis = analysis.model_copy(update={"analysis_id": analysis_id})
                db.execute(
                    "INSERT INTO analyses(analysis_id,brd_id,model_version_id,status,summary_json,created_at) VALUES(?,?,?,?,?,?)",
                    (analysis.analysis_id, analysis.brd_id, model_version_id, analysis.status, json.dumps(analysis.summary.model_dump()), now),
                )
                for issue in analysis.issues:
                    db.execute(
                        "INSERT INTO issues(issue_id,analysis_id,model_version_id,type,severity,title,description,reason,severity_reason,clarification_required,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                        (issue.issue_id, analysis.analysis_id, model_version_id, issue.type, issue.severity, issue.title, issue.description, issue.reason, issue.severity_reason, int(issue.clarification_required), now),
                    )
                    for requirement_id in issue.affected_requirements:
                        db.execute("INSERT INTO issue_requirements(analysis_id,issue_id,model_version_id,requirement_id) VALUES(?,?,?,?)", (analysis.analysis_id, issue.issue_id, model_version_id, requirement_id))
                for question in analysis.clarification_questions:
                    db.execute(
                        "INSERT INTO clarification_questions(question_id,analysis_id,issue_id,model_version_id,question,reason,priority,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (question.question_id, analysis.analysis_id, question.issue_id, model_version_id, question.question, question.reason, question.priority, "PENDING", now),
                    )
                    for requirement_id in question.affected_requirements:
                        db.execute("INSERT INTO question_requirements(analysis_id,question_id,model_version_id,requirement_id) VALUES(?,?,?,?)", (analysis.analysis_id, question.question_id, model_version_id, requirement_id))
                db.commit()
                return analysis
        except sqlite3.Error as exc:
            raise PersistenceError(f"analysis persistence failed: {exc}") from exc

    def get_analysis(self, analysis_id: str) -> RequirementsAnalysis:
        try:
            with self.connection() as db:
                row = db.execute("SELECT * FROM analyses WHERE analysis_id=?", (analysis_id,)).fetchone()
                if not row:
                    raise PersistenceError(f"no persisted analysis found for analysis_id {analysis_id}")
                issue_rows = db.execute("SELECT * FROM issues WHERE analysis_id=? ORDER BY rowid", (analysis_id,)).fetchall()
                question_rows = db.execute("SELECT * FROM clarification_questions WHERE analysis_id=? ORDER BY rowid", (analysis_id,)).fetchall()
                issues = []
                for issue in issue_rows:
                    refs = db.execute("SELECT requirement_id FROM issue_requirements WHERE analysis_id=? AND issue_id=? ORDER BY requirement_id", (analysis_id, issue["issue_id"])).fetchall()
                    issues.append({"issue_id": issue["issue_id"], "type": issue["type"], "severity": issue["severity"], "title": issue["title"], "description": issue["description"], "affected_requirements": [r["requirement_id"] for r in refs], "reason": issue["reason"], "clarification_required": bool(issue["clarification_required"]), "severity_reason": issue["severity_reason"]})
                questions = []
                for question in question_rows:
                    refs = db.execute("SELECT requirement_id FROM question_requirements WHERE analysis_id=? AND question_id=? ORDER BY requirement_id", (analysis_id, question["question_id"])).fetchall()
                    questions.append({"question_id": question["question_id"], "issue_id": question["issue_id"], "affected_requirements": [r["requirement_id"] for r in refs], "question": question["question"], "reason": question["reason"], "priority": question["priority"]})
                requirement_count = json.loads(row["summary_json"]).get("total_requirements_analyzed", 0)
                quality_status = "INVALID" if requirement_count == 0 else ("READY_FOR_CLARIFICATION" if questions else "READY")
                if any(item["severity"] == "CRITICAL" for item in issues):
                    quality_status = "NEEDS_REWORK"
                elif any(item["severity"] == "HIGH" for item in issues):
                    quality_status = "READY_FOR_CLARIFICATION"
                payload = {"brd_id": row["brd_id"], "analysis_id": row["analysis_id"], "status": row["status"], "summary": json.loads(row["summary_json"]), "issues": issues, "clarification_questions": questions, "quality_status": quality_status, "extraction_metadata": {"milestone": "2", "provider": "gemini", "persisted": "true"}}
                return RequirementsAnalysis.model_validate(payload)
        except sqlite3.Error as exc:
            raise PersistenceError(f"analysis retrieval failed: {exc}") from exc

    def audit(self, action: str, entity_type: str, entity_id: str, result: str = "SUCCESS", details: Optional[Dict[str, Any]] = None, actor_type: str = "system", actor_id: Optional[str] = None) -> None:
        try:
            with self.connection() as db:
                db.execute("INSERT INTO audit_logs(timestamp,actor_type,actor_id,action,entity_type,entity_id,result,details_json) VALUES(?,?,?,?,?,?,?,?)", (utc_now(), actor_type, actor_id, action, entity_type, entity_id, result, json.dumps(details or {})))
                db.commit()
        except sqlite3.Error as exc:
            raise PersistenceError(f"audit persistence failed: {exc}") from exc

    def create_hitl_session(self, analysis_id: str) -> Dict[str, Any]:
        import uuid
        session_id = "HITL-" + uuid.uuid4().hex[:12].upper()
        now = utc_now()
        try:
            with self.connection() as db:
                analysis = db.execute("SELECT brd_id FROM analyses WHERE analysis_id=?", (analysis_id,)).fetchone()
                if not analysis:
                    raise PersistenceError(f"no persisted analysis found for analysis_id {analysis_id}")
                questions = db.execute("SELECT question_id FROM clarification_questions WHERE analysis_id=? ORDER BY rowid", (analysis_id,)).fetchall()
                if not questions:
                    raise PersistenceError("analysis contains no clarification questions")
                db.execute("INSERT INTO hitl_sessions(session_id,analysis_id,brd_id,status,current_question_id,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (session_id, analysis_id, analysis["brd_id"], "ACTIVE", questions[0]["question_id"], now, now))
                db.commit()
            self.audit("HITL_SESSION_CREATED", "hitl_session", session_id, details={"analysis_id": analysis_id})
            return self.get_hitl_session(session_id)
        except sqlite3.Error as exc:
            raise PersistenceError(f"HITL session creation failed: {exc}") from exc

    def get_hitl_session(self, session_id: str) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM hitl_sessions WHERE session_id=?", (session_id,)).fetchone()
            if not row:
                raise PersistenceError(f"no HITL session found for session_id {session_id}")
            questions = db.execute("SELECT q.question_id,q.issue_id,q.question,q.reason,q.priority FROM clarification_questions q WHERE q.analysis_id=? ORDER BY q.rowid", (row["analysis_id"],)).fetchall()
            answers = db.execute("SELECT question_id,answer,created_at FROM hitl_answers WHERE session_id=?", (session_id,)).fetchall()
            answered = {item["question_id"] for item in answers}
            next_question = next((dict(item) for item in questions if item["question_id"] not in answered), None)
            return {"session_id": row["session_id"], "analysis_id": row["analysis_id"], "brd_id": row["brd_id"], "status": row["status"], "current_question_id": next_question["question_id"] if next_question else None, "follow_up_round": row["follow_up_round"], "questions": [dict(q) for q in questions], "answers": [dict(a) for a in answers]}

    def record_answer(self, session_id: str, question_id: str, answer: str) -> Dict[str, Any]:
        if not answer or not answer.strip():
            raise PersistenceError("answer must not be empty")
        try:
            with self.connection() as db:
                session = db.execute("SELECT * FROM hitl_sessions WHERE session_id=?", (session_id,)).fetchone()
                if not session:
                    raise PersistenceError(f"no HITL session found for session_id {session_id}")
                valid = db.execute("SELECT 1 FROM clarification_questions WHERE analysis_id=? AND question_id=?", (session["analysis_id"], question_id)).fetchone()
                if not valid:
                    raise PersistenceError("question does not belong to this HITL session")
                db.execute("INSERT OR IGNORE INTO hitl_answers(session_id,question_id,answer,created_at) VALUES(?,?,?,?)", (session_id, question_id, answer.strip(), utc_now()))
                remaining = db.execute("SELECT q.question_id FROM clarification_questions q LEFT JOIN hitl_answers a ON a.session_id=? AND a.question_id=q.question_id WHERE q.analysis_id=? AND a.question_id IS NULL ORDER BY q.rowid LIMIT 1", (session_id, session["analysis_id"])).fetchone()
                status = "ACTIVE" if remaining else "COMPLETED"
                db.execute("UPDATE hitl_sessions SET status=?,current_question_id=?,updated_at=? WHERE session_id=?", (status, remaining["question_id"] if remaining else None, utc_now(), session_id))
                db.commit()
            self.audit("HITL_ANSWER_RECORDED", "hitl_session", session_id, details={"question_id": question_id})
            if status == "COMPLETED":
                self.audit("HITL_SESSION_COMPLETED", "hitl_session", session_id)
                self._create_resolved_model(session_id)
            return self.get_hitl_session(session_id)
        except sqlite3.Error as exc:
            raise PersistenceError(f"answer persistence failed: {exc}") from exc

    def _create_resolved_model(self, session_id: str) -> None:
        with self.connection() as db:
            session = db.execute("SELECT analysis_id,brd_id FROM hitl_sessions WHERE session_id=?", (session_id,)).fetchone()
            analysis = db.execute("SELECT model_version_id FROM analyses WHERE analysis_id=?", (session["analysis_id"],)).fetchone()
            model_row = db.execute("SELECT model_json FROM requirements_models WHERE model_version_id=?", (analysis["model_version_id"],)).fetchone()
            model = RequirementsModel.model_validate_json(model_row["model_json"])
            answers = db.execute("SELECT question_id,answer FROM hitl_answers WHERE session_id=? ORDER BY answer_id", (session_id,)).fetchall()
        metadata = dict(model.extraction_metadata)
        metadata.update({"resolved": "true", "resolution_session_id": session_id, "human_answers": [dict(item) for item in answers]})
        resolved = model.model_copy(update={"extraction_metadata": metadata})
        new_version = self.save_requirements_model(resolved, "", "resolved-model")
        try:
            with self.connection() as db:
                db.execute("INSERT INTO resolved_requirements_models(session_id,model_version_id,source_model_version_id,created_at) VALUES(?,?,?,?)", (session_id, new_version, analysis["model_version_id"], utc_now()))
                db.commit()
            self.audit("RESOLVED_REQUIREMENTS_CREATED", "hitl_session", session_id, details={"source_model_version_id": analysis["model_version_id"], "resolved_model_version_id": new_version})
        except sqlite3.Error as exc:
            raise PersistenceError(f"resolved model persistence failed: {exc}") from exc
