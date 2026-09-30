from alembic import op
import sqlalchemy as sa

revision = "0002_project_workflows"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("owner_id", sa.String()),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "workflow_runs",
        sa.Column("run_id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("workflow_type", sa.String(), nullable=False),
        sa.Column("brd_id", sa.String()),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.String(), nullable=False),
        sa.Column("updated_at", sa.String(), nullable=False),
    )
    op.create_table(
        "workflow_events",
        sa.Column("event_id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("workflow_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_table(
        "workflow_artifacts",
        sa.Column("artifact_id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
        sa.Column("run_id", sa.String(), sa.ForeignKey("workflow_runs.run_id", ondelete="CASCADE"), nullable=False),
        sa.Column("markdown_path", sa.Text(), nullable=False),
        sa.Column("json_path", sa.Text(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )


def downgrade():
    for table in ["workflow_artifacts", "workflow_events", "workflow_runs", "projects"]:
        op.drop_table(table)
