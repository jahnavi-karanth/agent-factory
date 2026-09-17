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
                CREATE TABLE IF NOT EXISTS hitl_follow_up_questions (
                    session_id TEXT NOT NULL REFERENCES hitl_sessions(session_id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL,
                    issue_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    priority TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    PRIMARY KEY(session_id, question_id)
                );
                CREATE TABLE IF NOT EXISTS hitl_answer_requirements (
                    session_id TEXT NOT NULL REFERENCES hitl_sessions(session_id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL,
                    requirement_id TEXT NOT NULL,
                    PRIMARY KEY(session_id, question_id, requirement_id)
                );
                CREATE TABLE IF NOT EXISTS hitl_best_decisions (
                    session_id TEXT NOT NULL REFERENCES hitl_sessions(session_id) ON DELETE CASCADE,
                    question_id TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    reason TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(session_id, question_id)
                );
                CREATE TABLE IF NOT EXISTS resolved_requirements_models (
                    resolved_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL REFERENCES hitl_sessions(session_id),
                    model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    source_model_version_id INTEGER NOT NULL REFERENCES requirements_models(model_version_id),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    owner_id TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    filename TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    storage_path TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    error_message TEXT,
                    section_count INTEGER NOT NULL DEFAULT 0,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS document_sections (
                    section_id TEXT NOT NULL,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    title TEXT NOT NULL,
                    level INTEGER NOT NULL DEFAULT 1,
                    content TEXT NOT NULL,
                    chunk_count INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, section_id)
                );
                CREATE TABLE IF NOT EXISTS document_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
                    section_id TEXT NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    text TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'text',
                    page INTEGER,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_runs (
                    run_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    workflow_type TEXT NOT NULL,
                    brd_id TEXT,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_artifacts (
                    artifact_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(project_id),
                    run_id TEXT NOT NULL REFERENCES workflow_runs(run_id) ON DELETE CASCADE,
                    markdown_path TEXT NOT NULL,
                    json_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    intent TEXT NOT NULL,
                    structure_json TEXT NOT NULL,
                    when_to_use_json TEXT NOT NULL,
                    when_not_to_use_json TEXT NOT NULL,
                    prerequisites_json TEXT NOT NULL,
                    references_json TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    description TEXT,
                    strengths_json TEXT,
                    weaknesses_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_hitl_analysis ON hitl_sessions(analysis_id);
                CREATE INDEX IF NOT EXISTS idx_models_brd ON requirements_models(brd_id, version);
                CREATE INDEX IF NOT EXISTS idx_requirements_id ON requirements(requirement_id);
                CREATE INDEX IF NOT EXISTS idx_analyses_brd ON analyses(brd_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_issues_analysis ON issues(analysis_id);
                CREATE INDEX IF NOT EXISTS idx_questions_analysis ON clarification_questions(analysis_id);
                CREATE INDEX IF NOT EXISTS idx_runs_project ON workflow_runs(project_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_events_run ON workflow_events(project_id, run_id, event_id);
                CREATE INDEX IF NOT EXISTS idx_projects_owner ON projects(owner_id);
                CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_sections_doc ON document_sections(document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_doc ON document_chunks(document_id);
                CREATE INDEX IF NOT EXISTS idx_patterns_name ON patterns(name);
                """
            )
            # Ensure migration columns for projects if created with older schema
            columns = [col["name"] for col in db.execute("PRAGMA table_info(projects)").fetchall()]
            if "status" not in columns:
                db.execute("ALTER TABLE projects ADD COLUMN status TEXT NOT NULL DEFAULT 'draft'")
            if "updated_at" not in columns:
                db.execute("ALTER TABLE projects ADD COLUMN updated_at TEXT")
            db.commit()

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

    def list_brd_versions(self, brd_id: str) -> list[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT version_id,brd_id,version,parent_version_id,quality_status,status_reason,created_at FROM brd_versions WHERE brd_id=? ORDER BY version", (brd_id,)).fetchall()
            if not rows:
                raise PersistenceError(f"no persisted BRD versions found for brd_id {brd_id}")
            return [dict(row) for row in rows]

    def update_latest_quality_status(self, brd_id: str, status: str, reason: Optional[str] = None) -> None:
        with self.connection() as db:
            db.execute("UPDATE brd_versions SET quality_status=?,status_reason=? WHERE brd_id=? AND version=(SELECT MAX(version) FROM brd_versions WHERE brd_id=?)", (status, reason, brd_id, brd_id))
            db.commit()

    def list_audit(self, entity_type: Optional[str] = None, entity_id: Optional[str] = None) -> list[Dict[str, Any]]:
        with self.connection() as db:
            query = "SELECT id,timestamp,actor_type,actor_id,action,entity_type,entity_id,result,details_json,request_id FROM audit_logs WHERE 1=1"
            args: list[Any] = []
            if entity_type:
                query += " AND entity_type=?"
                args.append(entity_type)
            if entity_id:
                query += " AND entity_id=?"
                args.append(entity_id)
            query += " ORDER BY id"
            return [dict(row) for row in db.execute(query, args).fetchall()]

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
                db.execute("INSERT INTO hitl_sessions(session_id,analysis_id,brd_id,status,current_question_id,follow_up_round,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (session_id, analysis_id, analysis["brd_id"], "ACTIVE", questions[0]["question_id"], 0, now, now))
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
            questions = db.execute("SELECT q.question_id,q.issue_id,q.question,q.reason,q.priority FROM clarification_questions q WHERE q.analysis_id=? UNION ALL SELECT question_id,issue_id,question,reason,priority FROM hitl_follow_up_questions WHERE session_id=? ORDER BY question_id", (row["analysis_id"], session_id)).fetchall()
            answers = db.execute("SELECT question_id,answer,created_at FROM hitl_answers WHERE session_id=?", (session_id,)).fetchall()
            answered = {item["question_id"] for item in answers}
            next_question = next((dict(item) for item in questions if item["question_id"] not in answered), None)
            answer_payload = []
            for answer in answers:
                item = dict(answer)
                item["affected_requirements"] = [r["requirement_id"] for r in db.execute("SELECT requirement_id FROM hitl_answer_requirements WHERE session_id=? AND question_id=? ORDER BY requirement_id", (session_id, answer["question_id"])).fetchall()]
                answer_payload.append(item)
            decisions = [dict(item) for item in db.execute("SELECT question_id,decision,reason,created_at FROM hitl_best_decisions WHERE session_id=? ORDER BY question_id", (session_id,)).fetchall()]
            return {"session_id": row["session_id"], "analysis_id": row["analysis_id"], "brd_id": row["brd_id"], "status": row["status"], "current_question_id": next_question["question_id"] if next_question else None, "follow_up_round": row["follow_up_round"], "questions": [dict(q) for q in questions], "answers": answer_payload, "best_decisions": decisions}

    def record_answer(self, session_id: str, question_id: str, answer: str) -> Dict[str, Any]:
        if not answer or not answer.strip():
            raise PersistenceError("answer must not be empty")
        try:
            with self.connection() as db:
                session = db.execute("SELECT * FROM hitl_sessions WHERE session_id=?", (session_id,)).fetchone()
                if not session:
                    raise PersistenceError(f"no HITL session found for session_id {session_id}")
                valid = db.execute("SELECT 1 FROM clarification_questions WHERE analysis_id=? AND question_id=? UNION SELECT 1 FROM hitl_follow_up_questions WHERE session_id=? AND question_id=?", (session["analysis_id"], question_id, session_id, question_id)).fetchone()
                if not valid:
                    raise PersistenceError("question does not belong to this HITL session")
                db.execute("INSERT OR IGNORE INTO hitl_answers(session_id,question_id,answer,created_at) VALUES(?,?,?,?)", (session_id, question_id, answer.strip(), utc_now()))
                refs = db.execute("SELECT requirement_id FROM question_requirements q WHERE q.analysis_id=? AND q.question_id=? UNION SELECT requirement_id FROM issue_requirements i WHERE i.analysis_id=? AND i.issue_id=(SELECT issue_id FROM clarification_questions WHERE analysis_id=? AND question_id=?)", (session["analysis_id"], question_id, session["analysis_id"], session["analysis_id"], question_id)).fetchall()
                for ref in refs:
                    db.execute("INSERT OR IGNORE INTO hitl_answer_requirements(session_id,question_id,requirement_id) VALUES(?,?,?)", (session_id, question_id, ref["requirement_id"]))
                remaining = db.execute("SELECT allq.question_id FROM (SELECT q.question_id FROM clarification_questions q WHERE q.analysis_id=? UNION ALL SELECT question_id FROM hitl_follow_up_questions WHERE session_id=?) allq LEFT JOIN hitl_answers a ON a.session_id=? AND a.question_id=allq.question_id WHERE a.question_id IS NULL ORDER BY allq.question_id LIMIT 1", (session["analysis_id"], session_id, session_id)).fetchone()
                status = "ACTIVE" if remaining else "COMPLETED"
                db.execute("UPDATE hitl_sessions SET status=?,current_question_id=?,updated_at=? WHERE session_id=?", (status, remaining["question_id"] if remaining else None, utc_now(), session_id))
                db.commit()
            self.audit("HITL_ANSWER_RECORDED", "hitl_session", session_id, details={"question_id": question_id})
            return self.get_hitl_session(session_id)
        except sqlite3.Error as exc:
            raise PersistenceError(f"answer persistence failed: {exc}") from exc

    def add_follow_up_questions(self, session_id: str, questions: list[dict], round_number: int) -> Dict[str, Any]:
        if not questions:
            return self.get_hitl_session(session_id)
        try:
            with self.connection() as db:
                row = db.execute("SELECT 1 FROM hitl_sessions WHERE session_id=?", (session_id,)).fetchone()
                if not row:
                    raise PersistenceError(f"no HITL session found for session_id {session_id}")
                for item in questions:
                    db.execute("INSERT OR IGNORE INTO hitl_follow_up_questions(session_id,question_id,issue_id,question,reason,priority,round) VALUES(?,?,?,?,?,?,?)", (session_id, item["question_id"], item["issue_id"], item["question"], item["reason"], item["priority"], round_number))
                    for requirement_id in item.get("affected_requirements", []):
                        db.execute("INSERT OR IGNORE INTO hitl_answer_requirements(session_id,question_id,requirement_id) VALUES(?,?,?)", (session_id, item["question_id"], requirement_id))
                db.execute("UPDATE hitl_sessions SET status='ACTIVE',follow_up_round=?,current_question_id=?,updated_at=? WHERE session_id=?", (round_number, questions[0]["question_id"], utc_now(), session_id))
                db.commit()
            self.audit("FOLLOW_UP_ROUND_STARTED", "hitl_session", session_id, details={"round": round_number})
            for item in questions:
                self.audit("FOLLOW_UP_QUESTION_CREATED", "hitl_session", session_id, details={"round": round_number, "question_id": item["question_id"]})
            return self.get_hitl_session(session_id)
        except sqlite3.Error as exc:
            raise PersistenceError(f"follow-up persistence failed: {exc}") from exc

    def create_resolved_model(self, session_id: str) -> None:
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

    def save_best_decisions(self, session_id: str, decisions: list[dict]) -> None:
        try:
            with self.connection() as db:
                for item in decisions:
                    db.execute("INSERT OR REPLACE INTO hitl_best_decisions(session_id,question_id,decision,reason,created_at) VALUES(?,?,?,?,?)", (session_id, item["question_id"], item["decision"], item.get("reason") or "AI recommendation after the follow-up limit.", utc_now()))
                db.commit()
            self.audit("HITL_BEST_DECISIONS_RECORDED", "hitl_session", session_id, details={"count": len(decisions)})
        except sqlite3.Error as exc:
            raise PersistenceError(f"best-decision persistence failed: {exc}") from exc


    def create_project(self, project_id: str, name: str, owner_id: Optional[str] = None, status: str = "draft") -> Dict[str, Any]:
        now = utc_now()
        try:
            with self.connection() as db:
                db.execute("INSERT INTO projects(project_id,name,owner_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", (project_id, name, owner_id, status, now, now))
                db.commit()
            return {"project_id": project_id, "name": name, "owner_id": owner_id, "status": status, "created_at": now, "updated_at": now}
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(f"project already exists: {project_id}") from exc

    def get_project(self, project_id: str, owner_id: Optional[str] = None) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT project_id,name,owner_id,status,created_at,updated_at FROM projects WHERE project_id=? AND (? IS NULL OR owner_id=?)", (project_id, owner_id, owner_id)).fetchone()
            if not row:
                raise PersistenceError(f"no accessible project found for project_id {project_id}")
            res = dict(row)
            if not res.get("status"):
                res["status"] = "draft"
            return res

    def list_projects(self, owner_id: str) -> list[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT project_id,name,owner_id,status,created_at,updated_at FROM projects WHERE owner_id=? ORDER BY created_at DESC", (owner_id,)).fetchall()
            results = []
            for row in rows:
                item = dict(row)
                if not item.get("status"):
                    item["status"] = "draft"
                results.append(item)
            return results

    def update_project(self, project_id: str, owner_id: str, name: Optional[str] = None, status: Optional[str] = None) -> Dict[str, Any]:
        self.get_project(project_id, owner_id)
        now = utc_now()
        updates = []
        params = []
        if name is not None:
            updates.append("name=?")
            params.append(name)
        if status is not None:
            updates.append("status=?")
            params.append(status)
        if not updates:
            return self.get_project(project_id, owner_id)
        updates.append("updated_at=?")
        params.extend([now, project_id, owner_id])
        with self.connection() as db:
            db.execute(f"UPDATE projects SET {', '.join(updates)} WHERE project_id=? AND owner_id=?", params)
            db.commit()
        return self.get_project(project_id, owner_id)

    def save_document(
        self,
        project_id: str,
        document_id: str,
        filename: str,
        file_type: str,
        storage_path: str,
        status: str = "COMPLETED",
        error_message: Optional[str] = None,
        section_count: int = 0,
        chunk_count: int = 0,
    ) -> Dict[str, Any]:
        now = utc_now()
        with self.connection() as db:
            db.execute(
                "INSERT INTO documents(document_id,project_id,filename,file_type,storage_path,status,error_message,section_count,chunk_count,created_at,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(document_id) DO UPDATE SET status=excluded.status,error_message=excluded.error_message,"
                "section_count=excluded.section_count,chunk_count=excluded.chunk_count,updated_at=excluded.updated_at",
                (document_id, project_id, filename, file_type, storage_path, status, error_message, section_count, chunk_count, now, now),
            )
            db.commit()
        return self.get_document(project_id, document_id)

    def get_document(self, project_id: str, document_id: str) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT document_id,project_id,filename,file_type,storage_path,status,error_message,section_count,chunk_count,created_at,updated_at FROM documents WHERE project_id=? AND document_id=?", (project_id, document_id)).fetchone()
            if not row:
                raise PersistenceError(f"document {document_id} not found in project {project_id}")
            return dict(row)

    def save_document_sections_and_chunks(self, document_id: str, project_id: str, sections: list[Dict[str, Any]], chunks: list[Dict[str, Any]]) -> None:
        now = utc_now()
        with self.connection() as db:
            db.execute("BEGIN")
            db.execute("DELETE FROM document_sections WHERE document_id=?", (document_id,))
            db.execute("DELETE FROM document_chunks WHERE document_id=?", (document_id,))
            for sec in sections:
                db.execute(
                    "INSERT INTO document_sections(section_id,document_id,project_id,title,level,content,chunk_count,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (sec["section_id"], document_id, project_id, sec["title"], sec.get("level", 1), sec.get("content", ""), sec.get("chunk_count", 0), now),
                )
            for chk in chunks:
                db.execute(
                    "INSERT INTO document_chunks(chunk_id,document_id,section_id,project_id,text,kind,page,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (chk["chunk_id"], document_id, chk["section_id"], project_id, chk["text"], chk.get("kind", "text"), chk.get("page"), now),
                )
            db.execute("UPDATE documents SET section_count=?,chunk_count=?,status='COMPLETED',updated_at=? WHERE document_id=?", (len(sections), len(chunks), now, document_id))
            db.commit()

    def list_document_sections(self, project_id: str, document_id: str) -> list[Dict[str, Any]]:
        self.get_document(project_id, document_id)
        with self.connection() as db:
            rows = db.execute("SELECT section_id,document_id,project_id,title,level,content,chunk_count,created_at FROM document_sections WHERE document_id=? AND project_id=? ORDER BY rowid", (document_id, project_id)).fetchall()
            return [dict(row) for row in rows]

    def list_document_chunks(self, project_id: str, document_id: str) -> list[Dict[str, Any]]:
        self.get_document(project_id, document_id)
        with self.connection() as db:
            rows = db.execute("SELECT chunk_id,document_id,section_id,project_id,text,kind,page,created_at FROM document_chunks WHERE document_id=? AND project_id=? ORDER BY rowid", (document_id, project_id)).fetchall()
            return [dict(row) for row in rows]

    def create_workflow_run(self, project_id: str, brd_id: str) -> Dict[str, Any]:
        import uuid
        self.get_project(project_id)
        run_id = "RUN-" + uuid.uuid4().hex[:12].upper()
        now = utc_now()
        with self.connection() as db:
            db.execute("INSERT INTO workflow_runs(run_id,project_id,workflow_type,brd_id,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (run_id, project_id, "requirements", brd_id, "STARTING", now, now))
            db.commit()
        self.record_workflow_event(project_id, run_id, "workflow_started", {"brd_id": brd_id})
        return {"run_id": run_id, "project_id": project_id, "brd_id": brd_id, "status": "STARTING", "created_at": now}

    def create_user(self, user_id: str, email: str, password_hash: str) -> Dict[str, Any]:
        now = utc_now()
        try:
            with self.connection() as db:
                db.execute("INSERT INTO users(user_id,email,password_hash,created_at) VALUES(?,?,?,?)", (user_id, email.lower(), password_hash, now))
                db.commit()
            return {"user_id": user_id, "email": email.lower(), "created_at": now}
        except sqlite3.IntegrityError as exc:
            raise PersistenceError("email already registered") from exc

    def get_user_by_email(self, email: str) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT user_id,email,password_hash,created_at FROM users WHERE email=?", (email.lower(),)).fetchone()
            if not row:
                raise PersistenceError("user not found")
            return dict(row)

    def get_workflow_run(self, project_id: str, run_id: str) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT run_id,project_id,workflow_type,brd_id,status,error,created_at,updated_at FROM workflow_runs WHERE project_id=? AND run_id=?", (project_id, run_id)).fetchone()
            if not row:
                raise PersistenceError(f"no workflow run found for run_id {run_id}")
            return dict(row)

    def update_workflow_run(self, project_id: str, run_id: str, status: str, error: Optional[str] = None) -> None:
        with self.connection() as db:
            db.execute("UPDATE workflow_runs SET status=?,error=?,updated_at=? WHERE project_id=? AND run_id=?", (status, error, utc_now(), project_id, run_id))
            db.commit()

    def record_workflow_event(self, project_id: str, run_id: str, event_type: str, payload: Optional[Dict[str, Any]] = None) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO workflow_events(project_id,run_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)", (project_id, run_id, event_type, json.dumps(payload or {}), utc_now()))
            db.commit()

    def list_workflow_events(self, project_id: str, run_id: str) -> list[Dict[str, Any]]:
        self.get_workflow_run(project_id, run_id)
        with self.connection() as db:
            rows = db.execute("SELECT event_id,event_type,payload_json,created_at FROM workflow_events WHERE project_id=? AND run_id=? ORDER BY event_id", (project_id, run_id)).fetchall()
            return [{"event_id": row["event_id"], "event_type": row["event_type"], "payload": json.loads(row["payload_json"]), "created_at": row["created_at"]} for row in rows]

    def record_artifacts(self, project_id: str, run_id: str, markdown_path: str, json_path: str) -> None:
        with self.connection() as db:
            db.execute("INSERT INTO workflow_artifacts(project_id,run_id,markdown_path,json_path,created_at) VALUES(?,?,?,?,?)", (project_id, run_id, markdown_path, json_path, utc_now()))
            db.commit()

    def get_artifacts(self, project_id: str, run_id: str) -> Dict[str, Any]:
        self.get_workflow_run(project_id, run_id)
        with self.connection() as db:
            row = db.execute("SELECT markdown_path,json_path,created_at FROM workflow_artifacts WHERE project_id=? AND run_id=? ORDER BY artifact_id DESC LIMIT 1", (project_id, run_id)).fetchone()
            if not row:
                raise PersistenceError(f"no artifacts found for run_id {run_id}")
            return dict(row)

    def _row_to_pattern(self, row: sqlite3.Row) -> Dict[str, Any]:
        d = dict(row)
        return {
            "id": d["pattern_id"],
            "name": d["name"],
            "intent": d["intent"],
            "structure": json.loads(d["structure_json"]),
            "when_to_use": json.loads(d["when_to_use_json"]),
            "when_not_to_use": json.loads(d["when_not_to_use_json"]),
            "prerequisites": json.loads(d["prerequisites_json"]),
            "references": json.loads(d["references_json"]),
            "tags": json.loads(d["tags_json"]),
            "description": d.get("description"),
            "strengths": json.loads(d["strengths_json"]) if d.get("strengths_json") else None,
            "weaknesses": json.loads(d["weaknesses_json"]) if d.get("weaknesses_json") else None,
            "created_at": d["created_at"],
            "updated_at": d["updated_at"],
        }

    def save_pattern(
        self,
        pattern_id: str,
        name: str,
        intent: str,
        structure: Any,
        when_to_use: list,
        when_not_to_use: list,
        prerequisites: list,
        references: list,
        tags: list,
        description: Optional[str] = None,
        strengths: Optional[list] = None,
        weaknesses: Optional[list] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        struct_json = json.dumps(structure) if isinstance(structure, (list, dict)) else json.dumps(structure)
        try:
            with self.connection() as db:
                db.execute(
                    "INSERT INTO patterns(pattern_id,name,intent,structure_json,when_to_use_json,when_not_to_use_json,prerequisites_json,references_json,tags_json,description,strengths_json,weaknesses_json,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT(pattern_id) DO UPDATE SET name=excluded.name,intent=excluded.intent,structure_json=excluded.structure_json,when_to_use_json=excluded.when_to_use_json,when_not_to_use_json=excluded.when_not_to_use_json,prerequisites_json=excluded.prerequisites_json,references_json=excluded.references_json,tags_json=excluded.tags_json,description=excluded.description,strengths_json=excluded.strengths_json,weaknesses_json=excluded.weaknesses_json,updated_at=excluded.updated_at",
                    (
                        pattern_id,
                        name,
                        intent,
                        struct_json,
                        json.dumps(when_to_use or []),
                        json.dumps(when_not_to_use or []),
                        json.dumps(prerequisites or []),
                        json.dumps(references or []),
                        json.dumps(tags or []),
                        description,
                        json.dumps(strengths) if strengths is not None else None,
                        json.dumps(weaknesses) if weaknesses is not None else None,
                        now,
                        now,
                    ),
                )
                db.commit()
            return self.get_pattern(pattern_id)
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(f"pattern with name '{name}' already exists") from exc

    def get_pattern(self, pattern_id: str) -> Dict[str, Any]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM patterns WHERE pattern_id=? OR name=?", (pattern_id, pattern_id)).fetchone()
            if not row:
                raise PersistenceError(f"pattern {pattern_id} not found")
            return self._row_to_pattern(row)

    def get_pattern_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self.connection() as db:
            row = db.execute("SELECT * FROM patterns WHERE LOWER(name)=LOWER(?)", (name,)).fetchone()
            return self._row_to_pattern(row) if row else None

    def list_patterns(self, tag: Optional[str] = None) -> list[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute("SELECT * FROM patterns ORDER BY created_at ASC").fetchall()
            results = [self._row_to_pattern(row) for row in rows]
            if tag:
                clean_tag = tag.lower().strip()
                results = [p for p in results if any(clean_tag == t.lower().strip() for t in p.get("tags", []))]
            return results

    def update_pattern(self, pattern_id: str, **kwargs) -> Dict[str, Any]:
        existing = self.get_pattern(pattern_id)
        now = utc_now()
        p_id = existing["id"]
        
        name = kwargs.get("name") if kwargs.get("name") is not None else existing["name"]
        intent = kwargs.get("intent") if kwargs.get("intent") is not None else existing["intent"]
        structure = kwargs.get("structure") if kwargs.get("structure") is not None else existing["structure"]
        when_to_use = kwargs.get("when_to_use") if kwargs.get("when_to_use") is not None else existing["when_to_use"]
        when_not_to_use = kwargs.get("when_not_to_use") if kwargs.get("when_not_to_use") is not None else existing["when_not_to_use"]
        prerequisites = kwargs.get("prerequisites") if kwargs.get("prerequisites") is not None else existing["prerequisites"]
        references = kwargs.get("references") if kwargs.get("references") is not None else existing["references"]
        tags = kwargs.get("tags") if kwargs.get("tags") is not None else existing["tags"]
        description = kwargs.get("description") if "description" in kwargs else existing.get("description")
        strengths = kwargs.get("strengths") if "strengths" in kwargs else existing.get("strengths")
        weaknesses = kwargs.get("weaknesses") if "weaknesses" in kwargs else existing.get("weaknesses")

        try:
            with self.connection() as db:
                db.execute(
                    "UPDATE patterns SET name=?,intent=?,structure_json=?,when_to_use_json=?,when_not_to_use_json=?,prerequisites_json=?,references_json=?,tags_json=?,description=?,strengths_json=?,weaknesses_json=?,updated_at=? WHERE pattern_id=?",
                    (
                        name,
                        intent,
                        json.dumps(structure),
                        json.dumps(when_to_use),
                        json.dumps(when_not_to_use),
                        json.dumps(prerequisites),
                        json.dumps(references),
                        json.dumps(tags),
                        description,
                        json.dumps(strengths) if strengths is not None else None,
                        json.dumps(weaknesses) if weaknesses is not None else None,
                        now,
                        p_id,
                    ),
                )
                db.commit()
            return self.get_pattern(p_id)
        except sqlite3.IntegrityError as exc:
            raise PersistenceError(f"pattern name '{name}' is already taken by another pattern") from exc

    def delete_pattern(self, pattern_id: str) -> Dict[str, Any]:
        existing = self.get_pattern(pattern_id)
        p_id = existing["id"]
        with self.connection() as db:
            db.execute("DELETE FROM patterns WHERE pattern_id=?", (p_id,))
            db.commit()
        return existing

