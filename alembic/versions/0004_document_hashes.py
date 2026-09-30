from alembic import op
import sqlalchemy as sa

revision = "0004_document_hashes"
down_revision = "0005_patterns_table"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = [col["name"] for col in inspector.get_columns("documents")]
    if "content_hash" not in columns:
        with op.batch_alter_table("documents") as batch:
            batch.add_column(sa.Column("content_hash", sa.String(), nullable=True))
    indexes = [idx["name"] for idx in inspector.get_indexes("documents")]
    if "uq_documents_project_hash" not in indexes:
        op.create_index("uq_documents_project_hash", "documents", ["project_id", "content_hash"], unique=True, sqlite_where=sa.text("content_hash IS NOT NULL"))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    indexes = [idx["name"] for idx in inspector.get_indexes("documents")]
    if "uq_documents_project_hash" in indexes:
        op.drop_index("uq_documents_project_hash", table_name="documents")
    columns = [col["name"] for col in inspector.get_columns("documents")]
    if "content_hash" in columns:
        with op.batch_alter_table("documents") as batch:
            batch.drop_column("content_hash")

