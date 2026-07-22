"""create chunk_context_blocks and extend chunks for parent context (phase 4)

Phase 4 父子块上下文:
- chunk_context_blocks: 同一文档内连续子块合并成的父上下文块。
- chunks.sequence_no: 子块在文档内的稳定顺序。
- chunks.context_block_id: 子块归属的父上下文块。

父块仅用于检索后上下文补充, 不进入向量/BM25/RRF/Rerank。
外键策略:
- chunk_context_blocks.document_id -> documents.id ON DELETE CASCADE
  (删除 Document 时级联清理父上下文块)。
- chunks.context_block_id -> chunk_context_blocks.id ON DELETE SET NULL
  (删除父块时子块解引用, 不删子块)。

Revision ID: 0003_chunk_context_blocks
Revises: 0002_fix_cascade_fks
Create Date: 2026-07-22
"""
from alembic import op

revision = "0003_chunk_context_blocks"
down_revision = "0002_fix_cascade_fks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 创建父上下文块表
    op.execute(
        "CREATE TABLE IF NOT EXISTS chunk_context_blocks ("
        "    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),"
        "    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
        "    content TEXT NOT NULL,"
        "    start_sequence INTEGER NOT NULL,"
        "    end_sequence INTEGER NOT NULL,"
        "    token_count INTEGER DEFAULT 0,"
        "    content_hash VARCHAR(64) NOT NULL,"
        "    context_version VARCHAR(32) NOT NULL DEFAULT 'v1',"
        "    created_at TIMESTAMP NOT NULL DEFAULT now(),"
        "    updated_at TIMESTAMP NOT NULL DEFAULT now()"
        ")"
    )

    # 2) 给 chunks 加 sequence_no / context_block_id
    op.execute("ALTER TABLE chunks ADD COLUMN IF NOT EXISTS sequence_no INTEGER NOT NULL DEFAULT 0")
    op.execute(
        "ALTER TABLE chunks ADD COLUMN IF NOT EXISTS context_block_id UUID "
        "REFERENCES chunk_context_blocks(id) ON DELETE SET NULL"
    )

    # 3) 索引
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_document_sequence "
        "ON chunks (document_id, sequence_no)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunks_context_block_id "
        "ON chunks (context_block_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_context_blocks_document_id "
        "ON chunk_context_blocks (document_id)"
    )


def downgrade() -> None:
    # 先删外键列, 再删表(避免外键依赖冲突)
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS context_block_id")
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS sequence_no")
    op.execute("DROP TABLE IF EXISTS chunk_context_blocks")
