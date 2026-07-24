"""Move knowledge embeddings from pgvector to Milvus."""

import pgvector.sqlalchemy
import sqlalchemy as sa
from alembic import op

revision = "0004_milvus_vectorstore"
down_revision = "0003_enterprise_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("knowledge_chunks", "embedding")


def downgrade() -> None:
    op.add_column(
        "knowledge_chunks",
        sa.Column("embedding", pgvector.sqlalchemy.Vector(384), nullable=True),
    )
