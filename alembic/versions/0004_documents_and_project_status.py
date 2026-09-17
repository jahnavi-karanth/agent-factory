from alembic import op
import sqlalchemy as sa

revision = "0004_documents_and_project_status"
down_revision = "0003_users"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    
    # Check if status column exists in projects
    columns = [col["name"] for col in inspector.get_columns("projects")]
    if "status" not in columns:
        op.add_column("projects", sa.Column("status", sa.String(), nullable=False, server_default="draft"))
    if "updated_at" not in columns:
        op.add_column("projects", sa.Column("updated_at", sa.String()))
        
    if not inspector.has_table("documents"):
        op.create_table(
            "documents",
            sa.Column("document_id", sa.String(), primary_key=True),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
            sa.Column("filename", sa.String(), nullable=False),
            sa.Column("file_type", sa.String(), nullable=False),
            sa.Column("storage_path", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default="PENDING"),
            sa.Column("error_message", sa.Text()),
            sa.Column("section_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.Column("updated_at", sa.String(), nullable=False),
        )
        op.create_index("idx_documents_project", "documents", ["project_id", "created_at"])

    if not inspector.has_table("document_sections"):
        op.create_table(
            "document_sections",
            sa.Column("section_id", sa.String(), nullable=False),
            sa.Column("document_id", sa.String(), sa.ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
            sa.Column("title", sa.String(), nullable=False),
            sa.Column("level", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.String(), nullable=False),
            sa.PrimaryKeyConstraint("document_id", "section_id"),
        )
        op.create_index("idx_sections_doc", "document_sections", ["document_id"])

    if not inspector.has_table("document_chunks"):
        op.create_table(
            "document_chunks",
            sa.Column("chunk_id", sa.String(), primary_key=True),
            sa.Column("document_id", sa.String(), sa.ForeignKey("documents.document_id", ondelete="CASCADE"), nullable=False),
            sa.Column("section_id", sa.String(), nullable=False),
            sa.Column("project_id", sa.String(), sa.ForeignKey("projects.project_id"), nullable=False),
            sa.Column("text", sa.Text(), nullable=False),
            sa.Column("kind", sa.String(), nullable=False, server_default="text"),
            sa.Column("page", sa.Integer()),
            sa.Column("created_at", sa.String(), nullable=False),
        )
        op.create_index("idx_chunks_doc", "document_chunks", ["document_id"])


def downgrade():
    for table in ["document_chunks", "document_sections", "documents"]:
        op.drop_table(table)
