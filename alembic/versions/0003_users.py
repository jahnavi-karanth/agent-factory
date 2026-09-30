from alembic import op
import sqlalchemy as sa

revision = "0003_users"
down_revision = "0002_project_workflows"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("created_at", sa.String(), nullable=False),
    )
    op.create_index("idx_projects_owner", "projects", ["owner_id"])


def downgrade():
    op.drop_index("idx_projects_owner", table_name="projects")
    op.drop_table("users")
