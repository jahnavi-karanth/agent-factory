from alembic import op
import sqlalchemy as sa

revision = "0006_planning_tables"
down_revision = "0004_document_hashes"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    if not inspector.has_table("planning_runs"):
        op.create_table(
            "planning_runs",
            sa.Column("run_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
            sa.Column("workflow_type", sa.String(), nullable=False),
            sa.Column("source_model_version_id", sa.Integer(), nullable=True),
            sa.Column("resolved_model_version_id", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(), nullable=False),
            sa.Column("current_stage", sa.String(), nullable=False),
            sa.Column("planning_route", sa.String(), nullable=False),
            sa.Column("iteration_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("token_usage", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("approval_status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("rejection_feedback", sa.Text(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )
        op.create_index("idx_planning_runs_project", "planning_runs", ["project_id", "created_at"])

    if not inspector.has_table("selected_patterns"):
        op.create_table(
            "selected_patterns",
            sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.run_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("pattern_id", sa.String(), primary_key=True),
            sa.Column("pattern_name", sa.String(), nullable=False),
            sa.Column("rationale", sa.Text(), nullable=False),
            sa.Column("addressed_requirement_ids", sa.Text(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("created_at", sa.String(), nullable=False),
        )

    if not inspector.has_table("research_findings"):
        op.create_table(
            "research_findings",
            sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.run_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("finding_id", sa.String(), primary_key=True),
            sa.Column("source_type", sa.String(), nullable=False),
            sa.Column("citation_tag", sa.String(), nullable=False),
            sa.Column("claim", sa.Text(), nullable=False),
            sa.Column("evidence", sa.Text(), nullable=False),
            sa.Column("source_url", sa.Text(), nullable=True),
            sa.Column("document_id", sa.String(), nullable=True),
            sa.Column("section_id", sa.String(), nullable=True),
            sa.Column("pattern_id", sa.String(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("created_at", sa.String(), nullable=False),
        )

    if not inspector.has_table("architecture_documents"):
        op.create_table(
            "architecture_documents",
            sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.run_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("markdown_path", sa.Text(), nullable=True),
            sa.Column("markdown_content", sa.Text(), nullable=True),
            sa.Column("json_path", sa.Text(), nullable=True),
            sa.Column("structured_json", sa.Text(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.String(), nullable=False),
        )

    if not inspector.has_table("planning_tasks"):
        op.create_table(
            "planning_tasks",
            sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.run_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("task_id", sa.String(), primary_key=True),
            sa.Column("sequence_number", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("target_files", sa.Text(), nullable=False),
            sa.Column("acceptance_criteria", sa.Text(), nullable=False),
            sa.Column("dependency_task_ids", sa.Text(), nullable=False),
            sa.Column("pattern_ids", sa.Text(), nullable=False),
            sa.Column("requirement_ids", sa.Text(), nullable=False),
            sa.Column("research_citation_tags", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("status", sa.String(), nullable=False, server_default="PLANNED"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )

    if not inspector.has_table("planning_validation_results"):
        op.create_table(
            "planning_validation_results",
            sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.run_id", ondelete="CASCADE"), primary_key=True),
            sa.Column("validation_iteration", sa.Integer(), primary_key=True),
            sa.Column("passed", sa.Integer(), nullable=False),
            sa.Column("coverage_errors", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("ordering_errors", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("pattern_fidelity_errors", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("atomicity_errors", sa.Text(), nullable=False, server_default="[]"),
            sa.Column("details", sa.Text(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.String(), nullable=False),
        )

    if not inspector.has_table("planning_approval_events"):
        op.create_table(
            "planning_approval_events",
            sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("run_id", sa.String(), sa.ForeignKey("planning_runs.run_id", ondelete="CASCADE"), nullable=False),
            sa.Column("decision", sa.String(), nullable=False),
            sa.Column("feedback", sa.Text(), nullable=True),
            sa.Column("actor", sa.String(), nullable=True),
            sa.Column("created_at", sa.String(), nullable=False),
        )


def downgrade():
    for table in [
        "planning_approval_events",
        "planning_validation_results",
        "planning_tasks",
        "architecture_documents",
        "research_findings",
        "selected_patterns",
        "planning_runs",
    ]:
        op.drop_table(table)
