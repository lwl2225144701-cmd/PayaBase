"""create chunk_lexical tables (phase 3 lexical index)

词法索引持久化倒排索引: chunk_lexical_documents(每 chunk 一行)与
chunk_lexical_terms(每 chunk 每 term 一行, 含词频)。
外键级联(ON DELETE CASCADE)到 chunks / documents / knowledge_bases,
保证删除 Chunk / Document / KB 时词法索引自动清理。

使用 IF NOT EXISTS 以保证幂等: 既能在全新库建表, 也能在已由
Base.metadata.create_all 预建表的库上安全 no-op(并仍记录 alembic 版本)。
生产部署顺序: init_db(create_all) -> alembic upgrade head(记录版本/补索引)。

Revision ID: 0001_chunk_lexical
Revises:
Create Date: 2026-07-21
"""
from alembic import op

revision = "0001_chunk_lexical"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS chunk_lexical_documents ("
        "    chunk_id UUID PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,"
        "    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,"
        "    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,"
        "    token_count INTEGER DEFAULT 0,"
        "    content_hash VARCHAR(64) NOT NULL,"
        "    index_version VARCHAR(32) NOT NULL DEFAULT 'v1',"
        "    created_at TIMESTAMP NOT NULL DEFAULT now(),"
        "    updated_at TIMESTAMP NOT NULL DEFAULT now()"
        ")"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS chunk_lexical_terms ("
        "    chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,"
        "    knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,"
        "    term VARCHAR(255) NOT NULL,"
        "    term_frequency INTEGER DEFAULT 1,"
        "    PRIMARY KEY (chunk_id, knowledge_base_id, term)"
        ")"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_lexical_terms_kb_term "
        "ON chunk_lexical_terms (knowledge_base_id, term)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_chunk_lexical_terms_chunk "
        "ON chunk_lexical_terms (chunk_id)"
    )


def downgrade() -> None:
    # 先删子表(引用 chunks), 再删父表
    op.execute("DROP TABLE IF EXISTS chunk_lexical_terms")
    op.execute("DROP TABLE IF EXISTS chunk_lexical_documents")
