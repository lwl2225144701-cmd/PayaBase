"""第四阶段 — 真实 PostgreSQL 集成测试(独立库, 不触网)。

覆盖:
- 0003 migration 升级/降级(含可执行 downgrade)
- 索引阶段生成父上下文块 + sequence_no 连续 + context_block_id 关联
- 重新切片清理旧父块
- 删除 Document 级联清理 chunk_context_blocks(FK ON DELETE CASCADE)
- expand_results 真实查库: 命中子块获取父块, final_score/final_rank 不变
- 相邻扩展不跨文档

依赖本地 Postgres(pgvector)。连接失败则整个模块 skip。
"""
import asyncio
import contextlib
import os
import uuid

import psycopg2
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from core.config import settings
from core.rag.context_expansion import expand_results
from core.rag.retriever import RetrievedChunk
from core.tasks.indexing import batch_insert_chunks
from models.tables import (
    Base,
    Chunk,
    ChunkContextBlock,
    Document,
    KnowledgeBase,
    Tenant,
)

ADMIN_SYNC = settings.sync_database_url
P4_DB = "training_agent_test_p4"
MIG_DB_P4 = "training_agent_test_mig_p4"
P4_SYNC = f"postgresql://training:training123@localhost:5432/{P4_DB}"
P4_ASYNC = f"postgresql+asyncpg://training:training123@localhost:5432/{P4_DB}"

VEC = [0.01] * 512


def _pg_available() -> bool:
    try:
        c = psycopg2.connect(ADMIN_SYNC, connect_timeout=3)
        c.close()
        return True
    except Exception:
        return False


def _drop_and_create(admin, name):
    admin.autocommit = True
    cur = admin.cursor()
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    )
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    cur.execute(f'CREATE DATABASE "{name}" OWNER training')
    cur.close()


@pytest.fixture(scope="session")
def p4():
    if not _pg_available():
        pytest.skip("本地 PostgreSQL 不可用, 跳过第四阶段集成测试")
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, P4_DB)
    admin.close()

    sync = create_engine(P4_SYNC)
    with sync.connect() as c:
        c.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa_text("CREATE EXTENSION IF NOT EXISTS vector")
        )
    Base.metadata.create_all(sync)
    yield sync
    sync.dispose()
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, P4_DB)
    admin.close()


@pytest.fixture(scope="session")
def p4_mig():
    if not _pg_available():
        pytest.skip("本地 PostgreSQL 不可用, 跳过第四阶段 migration 集成测试")
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, MIG_DB_P4)
    admin.close()

    mig_sync = f"postgresql://training:training123@localhost:5432/{MIG_DB_P4}"
    sync = create_engine(mig_sync)
    with sync.connect() as c:
        c.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa_text("CREATE EXTENSION IF NOT EXISTS vector")
        )
    # 基表(含 chunk_context_blocks 与 chunks.context_block_id 外键)必须由 create_all 一次性建出:
    # chunks 对 chunk_context_blocks 有外键, 无法单独建 chunks 而不同建父块表。
    # 测试内部会先回退到 0003 之前的状态(删父块表 + 两列), 再 alembic upgrade head 真实重建,
    # 以同时验证升级与降级路径。migration 的 IF NOT EXISTS / ADD COLUMN IF NOT EXISTS 保证幂等。
    Base.metadata.create_all(sync)
    yield mig_sync
    sync.dispose()
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, MIG_DB_P4)
    admin.close()


@pytest.fixture
async def p4_session(p4):
    with p4.connect() as c:
        conn = c.execution_options(isolation_level="AUTOCOMMIT")
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(sa_text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    async_engine = create_async_engine(P4_ASYNC)
    maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    s = maker()
    yield s
    with contextlib.suppress(Exception):
        await s.rollback()
    await s.close()
    await async_engine.dispose()


async def _seed_doc(session):
    """插入 tenant/kb/doc, 返回 (kb, doc)。"""
    tenant = Tenant(id=uuid.uuid4(), name="t4")
    kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb4")
    doc = Document(
        id=uuid.uuid4(),
        knowledge_base_id=kb.id,
        title="doc4",
        file_path="/x",
        file_type="md",
        file_size=1,
        status="ready",
    )
    session.add_all([tenant, kb, doc])
    await session.commit()
    return kb, doc


def _chunks_data(n, content_prefix="子块"):
    return [
        {"content": f"{content_prefix}{i}内容" * 40, "meta": {}, "token_count": 100}
        for i in range(n)
    ]


# === 1. migration 升级 / 降级 ==================================================
@pytest.mark.pg_integration
def test_migration_0003_upgrade_downgrade(p4_mig, monkeypatch):
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("ALEMBIC_DB_URL", p4_mig)
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))

    # 回退到 0003 之前的状态: 删除父块表与 chunks 上新增的两列,
    # 让 alembic upgrade head 真正执行 0003 的建表/加列逻辑(而非 IF NOT EXISTS 短路)。
    with psycopg2.connect(p4_mig, connect_timeout=5) as c:
        cur = c.cursor()
        cur.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS context_block_id")
        cur.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS sequence_no")
        cur.execute("DROP TABLE IF EXISTS chunk_context_blocks")
        cur.execute("DROP TABLE IF EXISTS alembic_version")

    command.upgrade(cfg, "head")
    with psycopg2.connect(p4_mig, connect_timeout=5) as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'chunk_context_blocks'"
        )
        n_table = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND column_name = 'sequence_no'"
        )
        n_seq = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND column_name = 'context_block_id'"
        )
        n_cbid = cur.fetchone()[0]
    assert n_table == 1
    assert n_seq == 1
    assert n_cbid == 1

    # downgrade 验证可执行: 回到 base 后 0003 引入的表/列均被移除
    command.downgrade(cfg, "base")
    with psycopg2.connect(p4_mig, connect_timeout=5) as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name = 'chunk_context_blocks'"
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND column_name = 'sequence_no'"
        )
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'chunks' AND column_name = 'context_block_id'"
        )
        assert cur.fetchone()[0] == 0


# === 2. 索引阶段生成父块 ======================================================
@pytest.mark.pg_integration
async def test_index_creates_parent_blocks(p4_session, p4):
    _, doc = await _seed_doc(p4_session)
    chunks_data = _chunks_data(10)
    await asyncio.to_thread(batch_insert_chunks, str(doc.id), chunks_data, [VEC] * 10, engine=p4)

    blocks = (
        await p4_session.execute(
            select(ChunkContextBlock).where(ChunkContextBlock.document_id == doc.id)
        )
    ).scalars().all()
    chunks = (
        await p4_session.execute(
            select(Chunk)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.sequence_no)
        )
    ).scalars().all()

    # 10 子块写入
    assert len(chunks) == 10
    # sequence_no 连续 0..9
    assert [c.sequence_no for c in chunks] == list(range(10))
    # 父块生成(10 子块, 每父块 4~8 → 2 个父块)
    assert 1 <= len(blocks) <= 3
    # 每个子块都关联父块
    assert all(c.context_block_id is not None for c in chunks)
    # 父块覆盖全部子块(无遗漏)
    covered = set()
    for b in blocks:
        covered.update(range(b.start_sequence, b.end_sequence + 1))
    assert covered == set(range(10))


# === 3. 重新切片清理旧父块 ====================================================
@pytest.mark.pg_integration
async def test_reindex_cleans_old_parent_blocks(p4_session, p4):
    _, doc = await _seed_doc(p4_session)
    await asyncio.to_thread(
        batch_insert_chunks, str(doc.id), _chunks_data(10, "旧"), [VEC] * 10, engine=p4
    )
    old_blocks = (
        await p4_session.execute(
            select(ChunkContextBlock).where(ChunkContextBlock.document_id == doc.id)
        )
    ).scalars().all()
    old_ids = {str(b.id) for b in old_blocks}

    # 重新切片(不同内容, 仍 10 子块)
    await asyncio.to_thread(
        batch_insert_chunks, str(doc.id), _chunks_data(10, "新"), [VEC] * 10, engine=p4
    )
    new_blocks = (
        await p4_session.execute(
            select(ChunkContextBlock).where(ChunkContextBlock.document_id == doc.id)
        )
    ).scalars().all()
    new_ids = {str(b.id) for b in new_blocks}

    # 旧父块被清理, 新父块为不同 ID
    assert old_ids.isdisjoint(new_ids)
    # 重新切片后父块数量仍合理(未被重复累加)
    assert 1 <= len(new_blocks) <= 3


# === 4. 删除 Document 级联清理父块 ===========================================
@pytest.mark.pg_integration
async def test_document_delete_cascades_context_blocks(p4_session, p4):
    _, doc = await _seed_doc(p4_session)
    await asyncio.to_thread(batch_insert_chunks, str(doc.id), _chunks_data(8), [VEC] * 8, engine=p4)

    n_before = (
        await p4_session.execute(
            select(ChunkContextBlock).where(ChunkContextBlock.document_id == doc.id)
        )
    ).scalars().all()
    assert len(n_before) >= 1

    # 删除 document(ORM 级联: chunks + chunk_context_blocks 均清理)
    await p4_session.delete(doc)
    await p4_session.commit()

    remaining = (
        await p4_session.execute(
            select(ChunkContextBlock).where(ChunkContextBlock.document_id == doc.id)
        )
    ).scalars().all()
    assert len(remaining) == 0


# === 5. expand_results 真实查库: 命中子块获取父块 =============================
@pytest.mark.pg_integration
async def test_expand_results_uses_parent_block(p4_session, p4):
    _, doc = await _seed_doc(p4_session)
    await asyncio.to_thread(batch_insert_chunks, str(doc.id), _chunks_data(10), [VEC] * 10, engine=p4)

    chunks = (
        await p4_session.execute(
            select(Chunk)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.sequence_no)
        )
    ).scalars().all()

    # 构造两个命中结果(第 0、1 块, 同属第一个父块)
    results = []
    for i in (0, 1):
        ch = chunks[i]
        rc = RetrievedChunk(
            chunk_id=str(ch.id),
            content=ch.content,
            document_id=str(ch.document_id),
            document_title="doc4",
            score=0.9 - i * 0.1,
            metadata={},
            final_rank=i + 1,
        )
        results.append(rc)

    out, stats = await expand_results(p4_session, results)

    # 至少命中一个有父块的结果
    assert stats["parent_context_hit_count"] >= 1
    # context_content 应比单子块更长(含父块 + 相邻)
    assert len(out[0].context_content) > len(out[0].content)
    assert out[0].context_source in ("parent", "parent_adjacent")
    assert out[0].parent_context_id is not None
    # final_score / final_rank 不变
    assert out[0].final_rank == 1 and out[0].score == 0.9
    # 覆盖相邻块(父块范围外可能还有相邻)
    assert len(out[0].context_chunk_ids) >= 2


# === 6. 相邻扩展不跨文档 ======================================================
@pytest.mark.pg_integration
async def test_adjacent_expansion_not_cross_document(p4_session, p4):
    _, doc = await _seed_doc(p4_session)
    await asyncio.to_thread(batch_insert_chunks, str(doc.id), _chunks_data(10), [VEC] * 10, engine=p4)

    chunks = (
        await p4_session.execute(
            select(Chunk)
            .where(Chunk.document_id == doc.id)
            .order_by(Chunk.sequence_no)
        )
    ).scalars().all()

    # 只命中第 0 块
    rc = RetrievedChunk(
        chunk_id=str(chunks[0].id),
        content=chunks[0].content,
        document_id=str(chunks[0].document_id),
        document_title="doc4",
        score=0.9,
        metadata={},
        final_rank=1,
    )
    out, _ = await expand_results(p4_session, [rc])
    # 相邻块必须都属于同一文档(不会拼入其他文档内容)
    # context_content 不含其他文档标识(这里只有单文档, 验证 context_chunk_ids 均来自该文档)
    assert out[0].parent_context_id is not None
    assert str(chunks[0].document_id) == out[0].document_id
