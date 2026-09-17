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
        question_map = {item.get("question_id"): item for item in state.get("analysis", {}).get("clarification_questions", [])}
        requirements = list(model.requirements)
        by_id = {item.id: index for index, item in enumerate(requirements)}
        for answer in state.get("human_answers", []):
            question = question_map.get(answer.get("question_id"), {})
            for requirement_id in question.get("affected_requirements", []):
                index = by_id.get(requirement_id)
                if index is not None:
                    original = requirements[index]
                    clarification = f"{original.description} Clarification decision (human-provided): {str(answer.get('answer', '')).strip()}"
                    requirements[index] = original.model_copy(update={"description": clarification})
        feedback = str(state.get("rejection_feedback", "")).strip()
        if feedback and requirements:
            original = requirements[0]
            requirements[0] = original.model_copy(update={"description": f"{original.description} Revision feedback to address (human-provided): {feedback}"})
        metadata = dict(model.extraction_metadata)
        metadata.update({"resolved": "true", "workflow_run_id": state["run_id"], "project_id": state["project_id"], "human_answers": state.get("human_answers", []), "ai_recommendations": state.get("ai_recommendations", []), "revision_count": state.get("revision_count", 0), "rejection_feedback": state.get("rejection_feedback", "")})
        resolved = model.model_copy(update={"requirements": requirements, "extraction_metadata": metadata})
        return {"resolved_requirements": resolved.model_dump(mode="json"), "status": "RESOLVED"}

    def approval_gate(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        response = interrupt({"type": "approval_request", "request_id": f"{state['run_id']}:approval:{state.get('revision_count', 0)}", "run_id": state["run_id"], "requirements": state["resolved_requirements"], "revision_count": state.get("revision_count", 0)})
        decision = response if isinstance(response, dict) else {"decision": str(response)}
        normalized = str(decision.get("decision", "")).upper()
        if normalized == "REJECT":
            return {"approval_status": "REJECTED", "rejection_feedback": str(decision.get("feedback", "")), "revision_count": state.get("revision_count", 0) + 1, "status": "REVISION_REQUESTED"}
        return {"approval_status": "APPROVED", "status": "APPROVED"}

    def route_after_approval(self, state: RequirementsWorkflowState) -> str:
        if state.get("approval_status") == "REJECTED":
            if state.get("revision_count", 0) > 3:
                return "finalize_artifacts"
            return "resolve_requirements"
        return "finalize_artifacts"

    def finalize_artifacts(self, state: RequirementsWorkflowState) -> Dict[str, Any]:
        base = Path("data") / "projects" / state["project_id"] / "runs" / state["run_id"]
        base.mkdir(parents=True, exist_ok=True)
        model = RequirementsModel.model_validate(state["resolved_requirements"])
        json_path = base / "Requirements.json"
        md_path = base / "Requirements.md"
        json_path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
        lines = [f"# {model.title or 'Requirements'}", "", f"BRD ID: {model.brd_id}", "", "## Requirements", ""]
        lines.extend(f"- **{item.id}** ({item.type}): {item.description}" for item in model.requirements)
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.repository.record_workflow_event(state["project_id"], state["run_id"], "workflow_completed", {"requirements_json": str(json_path), "requirements_md": str(md_path)})
        self.repository.record_artifacts(state["project_id"], state["run_id"], str(md_path), str(json_path))
        return {"status": "COMPLETED"}
