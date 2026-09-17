from alembic import op
import sqlalchemy as sa

revision = "0005_patterns_table"
down_revision = "0004_documents_and_project_status"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("patterns"):
        op.create_table(
            "patterns",
            sa.Column("pattern_id", sa.String(), primary_key=True),
            sa.Column("name", sa.String(), nullable=False, unique=True),
            sa.Column("intent", sa.Text(), nullable=False),
            sa.Column("structure_json", sa.Text(), nullable=False),
            sa.Column("when_to_use_json", sa.Text(), nullable=False),
            sa.Column("when_not_to_use_json", sa.Text(), nullable=False),
            sa.Column("prerequisites_json", sa.Text(), nullable=False),
            sa.Column("references_json", sa.Text(), nullable=False),
            sa.Column("tags_json", sa.Text(), nullable=False),
            sa.Column("description", sa.Text()),
            sa.Column("strengths_json", sa.Text()),
            sa.Column("weaknesses_json", sa.Text()),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )
        op.create_index("idx_patterns_name", "patterns", ["name"])


def downgrade():
    op.drop_table("patterns")
