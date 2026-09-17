from alembic import op
import sqlalchemy as sa

revision = "0004_document_hashes"
down_revision = "0005_patterns_table"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("documents") as batch:
        batch.add_column(sa.Column("content_hash", sa.String(), nullable=True))
    op.create_index("uq_documents_project_hash", "documents", ["project_id", "content_hash"], unique=True, sqlite_where=sa.text("content_hash IS NOT NULL"))


def downgrade():
    op.drop_index("uq_documents_project_hash", table_name="documents")
    with op.batch_alter_table("documents") as batch:
        batch.drop_column("content_hash")
