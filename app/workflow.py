from __future__ import annotations

import json
import sqlite3
import os
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .analysis_models import RequirementsAnalysis
from .analyzer import RequirementsAnalyzer
from .models import RequirementsModel
from .repository import SQLiteRepository, utc_now


class RequirementsWorkflowState(TypedDict, total=False):
    project_id: str
    run_id: str
    brd_id: str
    model_version_id: int
    requirements: Dict[str, Any]
    analysis: Dict[str, Any]
    clarification_questions: list[Dict[str, Any]]
    human_answers: list[Dict[str, Any]]
    follow_up_round: int
    ai_recommendations: list[Dict[str, Any]]
    resolved_requirements: Dict[str, Any]
    approval_status: str
    rejection_feedback: str
    revision_count: int
    status: str
    error: Optional[str]


class RequirementsWorkflow:
    """LangGraph orchestration around the existing M1/M2/M3 business services."""

    def __init__(self, repository: SQLiteRepository, analyzer: RequirementsAnalyzer):
        self.repository = repository
        self.analyzer = analyzer
        self._graph = None
        self._connection: Optional[sqlite3.Connection] = None

    def _checkpointer(self) -> SqliteSaver:
        if self._connection is None:
            path = self.repository.path
            if path == ":memory:":
                self._connection = sqlite3.connect(":memory:", check_same_thread=False)
            else:
                self._connection = sqlite3.connect(path, check_same_thread=False)
            self._connection.row_factory = sqlite3.Row
        saver = SqliteSaver(self._connection)
        saver.setup()
        return saver

    def graph(self):
        if self._graph is not None:
            return self._graph
        builder = StateGraph(RequirementsWorkflowState)
        builder.add_node("load_validate_input", self.load_validate_input)
        builder.add_node("requirements_analysis", self.requirements_analysis)
        builder.add_node("clarification_hitl", self.clarification_hitl)
        builder.add_node("resolve_requirements", self.resolve_requirements)
        builder.add_node("approval_gate", self.approval_gate)
        builder.add_node("finalize_artifacts", self.finalize_artifacts)
        builder.add_edge(START, "load_validate_input")
        builder.add_edge("load_validate_input", "requirements_analysis")
        builder.add_conditional_edges("requirements_analysis", self.route_after_analysis, {"clarification_hitl": "clarification_hitl", "resolve_requirements": "resolve_requirements"})
        builder.add_conditional_edges("clarification_hitl", self.route_after_clarification, {"clarification_hitl": "clarification_hitl", "resolve_requirements": "resolve_requirements"})
        builder.add_edge("resolve_requirements", "approval_gate")
        builder.add_conditional_edges("approval_gate", self.route_after_approval, {"resolve_requirements": "resolve_requirements", "finalize_artifacts": "finalize_artifacts"})
        builder.add_edge("finalize_artifacts", END)
        self._graph = builder.compile(checkpointer=self._checkpointer())
        return self._graph

    def config(self, run_id: str) -> Dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}

    def start(self, project_id: str, run_id: str, brd_id: str) -> Dict[str, Any]:
        return self.graph().invoke({"project_id": project_id, "run_id": run_id, "brd_id": brd_id, "status": "STARTING", "revision_count": 0, "human_answers": [], "ai_recommendations": []}, config=self.config(run_id))

    def resume(self, run_id: str, payload: Any) -> Dict[str, Any]:
        return self.graph().invoke(Command(resume=payload), config=self.config(run_id))

    def pending_interrupt(self, run_id: str) -> Any:
        snapshot = self.graph().get_state(self.config(run_id))
        return snapshot.tasks[0].interrupts[0].value if snapshot.tasks and snapshot.tasks[0].interrupts else None

    def load_validate_input(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        model, version_id = self.repository.get_requirements_model(state["brd_id"])
        return {"model_version_id": version_id, "requirements": model.model_dump(mode="json"), "status": "INPUT_LOADED"}

    def requirements_analysis(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        model = RequirementsModel.model_validate(state["requirements"])
        analysis = self.analyzer.analyze(model)
        return {"analysis": analysis.model_dump(mode="json"), "clarification_questions": [item.model_dump(mode="json") for item in analysis.clarification_questions], "status": "ANALYZED"}

    def route_after_analysis(self, state: RequirementsWorkflowState) -> str:
        return "clarification_hitl" if state.get("clarification_questions") else "resolve_requirements"

    def clarification_hitl(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        questions = state.get("clarification_questions", [])
        answers = state.get("human_answers", [])
        answered = {item.get("question_id") for item in answers}
        pending = [item for item in questions if item.get("question_id") not in answered]
        if pending:
            response = interrupt({"type": "clarification_request", "request_id": f"{state['run_id']}:clarification:{state.get('follow_up_round', 0)}", "run_id": state["run_id"], "questions": pending, "answers": answers, "follow_up_round": state.get("follow_up_round", 0)})
            incoming = response if isinstance(response, list) else [response]
            return {"human_answers": answers + [item for item in incoming if isinstance(item, dict)], "status": "CLARIFICATION_RECEIVED"}
        return {"status": "CLARIFICATION_COMPLETED"}

    def route_after_clarification(self, state: RequirementsWorkflowState) -> str:
        questions = state.get("clarification_questions", [])
        answers = state.get("human_answers", [])
        return "clarification_hitl" if len(answers) < len(questions) else "resolve_requirements"

    def resolve_requirements(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        model = RequirementsModel.model_validate(state["requirements"])

        # Build question map searching across state sources
        all_questions = list(state.get("clarification_questions", []))
        if "analysis" in state and isinstance(state["analysis"], dict):
            all_questions.extend(state["analysis"].get("clarification_questions", []))

        question_map = {}
        for q in all_questions:
            if isinstance(q, dict):
                qid = q.get("question_id") or q.get("id")
                if qid:
                    question_map[qid] = q

        requirements = list(model.requirements)
        by_id = {item.id: index for index, item in enumerate(requirements)}

        clarifications_list = []
        for answer in state.get("human_answers", []):
            if not isinstance(answer, dict):
                continue
            qid = answer.get("question_id") or answer.get("id")
            ans_text = str(answer.get("answer", "")).strip()
            q_obj = question_map.get(qid, {})
            q_text = q_obj.get("question", f"Clarification ({qid})")

            clarifications_list.append({
                "question_id": qid,
                "question": q_text,
                "answer": ans_text
            })

            affected = q_obj.get("affected_requirements", [])
            if affected:
                for requirement_id in affected:
                    index = by_id.get(requirement_id)
                    if index is not None:
                        original = requirements[index]
                        clarification = f"{original.description} | Clarification decision ({qid}): {ans_text}"
                        requirements[index] = original.model_copy(update={"description": clarification})
            else:
                if requirements:
                    original = requirements[0]
                    clarification = f"{original.description} | Clarification ({q_text}): {ans_text}"
                    requirements[0] = original.model_copy(update={"description": clarification})

        feedback = str(state.get("rejection_feedback", "")).strip()
        if feedback and requirements:
            original = requirements[0]
            requirements[0] = original.model_copy(update={"description": f"{original.description} | Revision feedback: {feedback}"})

        metadata = dict(model.extraction_metadata or {})
        metadata.update({
            "resolved": "true",
            "workflow_run_id": state["run_id"],
            "project_id": state["project_id"],
            "human_answers": state.get("human_answers", []),
            "human_clarifications": clarifications_list,
            "ai_recommendations": state.get("ai_recommendations", []),
            "revision_count": state.get("revision_count", 0),
            "rejection_feedback": state.get("rejection_feedback", "")
        })

        resolved = model.model_copy(update={"requirements": requirements, "extraction_metadata": metadata})
        return {"resolved_requirements": resolved.model_dump(mode="json"), "status": "RESOLVED"}

    def approval_gate(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        all_questions = list(state.get("clarification_questions", []))
        if "analysis" in state and isinstance(state["analysis"], dict):
            all_questions.extend(state["analysis"].get("clarification_questions", []))

        q_map = {}
        for q in all_questions:
            if isinstance(q, dict):
                qid = q.get("question_id") or q.get("id")
                if qid:
                    q_map[qid] = q.get("question", "")

        clarifications_summary = []
        for ans in state.get("human_answers", []):
            if isinstance(ans, dict):
                qid = ans.get("question_id") or ans.get("id")
                clarifications_summary.append({
                    "question_id": qid,
                    "question": q_map.get(qid, f"Clarification Question ({qid})"),
                    "answer": ans.get("answer", "")
                })

        req_model = state.get("resolved_requirements", {})
        req_list = req_model.get("requirements", []) if isinstance(req_model, dict) else []
        requirements_summary = [
            {
                "id": req.get("id"),
                "type": req.get("type"),
                "description": req.get("description")
            }
            for req in req_list if isinstance(req, dict)
        ]

        response = interrupt({
            "type": "approval_request",
            "request_id": f"{state['run_id']}:approval:{state.get('revision_count', 0)}",
            "run_id": state["run_id"],
            "requirements": state["resolved_requirements"],
            "clarification_summary": clarifications_summary,
            "requirements_summary": requirements_summary,
            "revision_count": state.get("revision_count", 0),
        })
        decision = response if isinstance(response, dict) else {"decision": str(response)}
        normalized = str(decision.get("decision", "")).strip().upper()
        if normalized == "REJECT":
            return {"approval_status": "REJECTED", "rejection_feedback": str(decision.get("feedback", "")), "revision_count": state.get("revision_count", 0) + 1, "status": "REVISION_REQUESTED"}
        elif normalized == "APPROVE":
            return {"approval_status": "APPROVED", "status": "APPROVED"}
        return {"approval_status": "PAUSED", "status": "PAUSED"}

    def route_after_approval(self, state: RequirementsWorkflowState) -> str:
        if state.get("approval_status") == "REJECTED":
            if state.get("revision_count", 0) > 3:
                return "finalize_artifacts"
            return "resolve_requirements"
        elif state.get("approval_status") == "APPROVED":
            return "finalize_artifacts"
        return "approval_gate"

    def finalize_artifacts(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        run_dir = Path("data") / "projects" / state["project_id"] / "runs" / state["run_id"]
        run_dir.mkdir(parents=True, exist_ok=True)

        project_dir = Path("data") / "projects" / state["project_id"]
        project_dir.mkdir(parents=True, exist_ok=True)

        model = RequirementsModel.model_validate(state["resolved_requirements"])

        # Save resolved model version into SQLite DB for GET /projects/{project_id}/requirements
        try:
            self.repository.save_requirements_model(model, model.model_dump_json(), "markdown")
        except Exception:
            pass

        # Build Markdown content
        lines = [f"# {model.title or 'Requirements'}", "", f"BRD ID: {model.brd_id}", "", "## Goals", ""]
        lines.extend(f"- {item}" for item in model.business_objectives or ([model.business_problem] if model.business_problem else ["Not specified"]))
        lines.extend(["", "## Personas", ""])
        lines.extend(f"- {item}" for item in (model.stakeholders + model.user_roles) or ["Not specified"])
        lines.extend(["", "## Functional Requirements", ""])
        lines.extend(f"- **{item.id}**: {item.description}" for item in model.requirements if item.type == "functional")
        lines.extend(["", "## Non-Functional Requirements", ""])
        lines.extend(f"- {item}" for item in model.non_functional_requirements or [item.description for item in model.requirements if item.type == "non_functional"] or ["Not specified"])
        lines.extend(["", "## Constraints", ""])
        lines.extend(f"- {item}" for item in model.constraints or ["Not specified"])

        # Add Human Clarifications Section
        human_clarifications = model.extraction_metadata.get("human_clarifications", [])
        lines.extend(["", "## Human Clarifications & Decisions", ""])
        if human_clarifications:
            for item in human_clarifications:
                q_text = item.get("question", item.get("question_id", "Question"))
                ans = item.get("answer", "")
                lines.append(f"- **Q**: {q_text}\n  **A**: {ans}")
        else:
            lines.append("- No clarification questions were required.")

        lines.extend(["", "## Out-of-Scope", "", "- Not specified", "", "## Open Questions", ""])
        lines.extend(f"- {item}" for item in model.assumptions + model.success_criteria or ["Not specified"])

        md_text = "\n".join(lines) + "\n"
        json_text = model.model_dump_json(indent=2)

        # Save in run directory
        run_json_path = run_dir / "Requirements.json"
        run_md_path = run_dir / "Requirements.md"
        run_json_path.write_text(json_text, encoding="utf-8")
        run_md_path.write_text(md_text, encoding="utf-8")

        # Save in project root directory
        proj_json_path = project_dir / "Requirements.json"
        proj_md_path = project_dir / "Requirements.md"
        proj_json_path.write_text(json_text, encoding="utf-8")
        proj_md_path.write_text(md_text, encoding="utf-8")

        self.repository.record_workflow_event(state["project_id"], state["run_id"], "workflow_completed", {"requirements_json": str(run_json_path), "requirements_md": str(run_md_path)})
        self.repository.record_artifacts(state["project_id"], state["run_id"], str(run_md_path), str(run_json_path))
        return {"status": "COMPLETED"}
