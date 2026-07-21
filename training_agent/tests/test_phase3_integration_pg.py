"""第三阶段 — 真实 PostgreSQL 集成测试(不再 mock DB)。

覆盖:
- migration 建表(独立库跑 alembic upgrade / downgrade, 含可执行 downgrade)
- 回填(index_document_async 写入词法索引)
- BM25 查询(向量为空时纯 BM25 命中)
- metadata / document_id 过滤(白名单, 防动态 SQL 注入)
- Chunk / Document / KB 删除级联清理词法索引(FK ON DELETE CASCADE)
- batch_replace 的 chunk_id 一致性(ORM Chunk 与词法索引复用同一 ID)
- Embedding 失败后 BM25 单路降级(双路都失败才返回空)

依赖本地 Postgres(pgvector)。连接失败则整个模块 skip, 不阻塞 CI。
"""
import contextlib
import os
import uuid

import psycopg2
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from core.config import settings
from core.embedding.client import EmbeddingClient
from core.infrastructure.db.repositories import (
    ChunkRepositoryImpl,
    DocumentRepositoryImpl,
    KnowledgeBaseRepositoryImpl,
)
from core.rag.lexical_index import index_document_async
from core.rag.retriever import Retriever
from models.tables import (
    Base,
    Chunk,
    ChunkLexicalDocument,
    ChunkLexicalTerm,
    Document,
    KnowledgeBase,
    Tenant,
)

ADMIN_SYNC = settings.sync_database_url
TEST_DB = "training_agent_test"
MIG_DB = "training_agent_test_mig"
TEST_SYNC = f"postgresql://training:training123@localhost:5432/{TEST_DB}"
TEST_ASYNC = f"postgresql+asyncpg://training:training123@localhost:5432/{TEST_DB}"


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
    cur.execute(f'DROP DATABASE IF EXISTS "{name}"')
    cur.execute(f'CREATE DATABASE "{name}" OWNER training')
    cur.close()


@pytest.fixture(scope="session")
def pg():
    if not _pg_available():
        pytest.skip("本地 PostgreSQL 不可用, 跳过第三阶段集成测试")
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, TEST_DB)
    admin.close()

    sync = create_engine(TEST_SYNC)
    with sync.connect() as c:
        c.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa_text("CREATE EXTENSION IF NOT EXISTS vector")
        )
    # 全量建表(含 chunk_lexical, 由 ORM 模型定义; migration 用 IF NOT EXISTS 幂等)
    Base.metadata.create_all(sync)

    yield {"sync": sync}

    sync.dispose()
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, TEST_DB)  # DROP 顺带清理
    admin.close()


@pytest.fixture(scope="session")
def pg_mig():
    if not _pg_available():
        pytest.skip("本地 PostgreSQL 不可用, 跳过 migration 集成测试")
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, MIG_DB)
    admin.close()

    mig_sync = f"postgresql://training:training123@localhost:5432/{MIG_DB}"
    sync = create_engine(mig_sync)
    with sync.connect() as c:
        c.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa_text("CREATE EXTENSION IF NOT EXISTS vector")
        )
    # 仅建父表(排除 chunk_lexical), 由 migration 创建, 验证 migration 的 FK 引用成立
    parent_tables = [
        t
        for t in Base.metadata.tables.values()
        if t.name not in ("chunk_lexical_documents", "chunk_lexical_terms")
    ]
    Base.metadata.create_all(sync, tables=parent_tables)

    yield mig_sync

    sync.dispose()
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, MIG_DB)
    admin.close()


@pytest.fixture
async def session(pg):
    # 每个测试前清空所有表(独立连接, 不影响测试事务)
    with pg["sync"].connect() as c:
        conn = c.execution_options(isolation_level="AUTOCOMMIT")
        names = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        conn.execute(sa_text(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE"))
    # async 引擎必须在当前测试的 event loop 内创建(避免跨 loop 的 asyncpg 错误)
    async_engine = create_async_engine(TEST_ASYNC)
    maker = async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
    s = maker()
    yield s
    with contextlib.suppress(Exception):
        await s.rollback()
    await s.close()
    await async_engine.dispose()


async def _seed(session, status="ready", chunks=None, tenant=None, kb=None, doc=None):
    """插入 tenant/kb/doc(可选复用) + chunks, 并构建词法索引, 返回 (tenant, kb, doc)。"""
    if tenant is None:
        tenant = Tenant(id=uuid.uuid4(), name="t")
        session.add(tenant)
    if kb is None:
        kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb")
        session.add(kb)
    if doc is None:
        doc = Document(
            id=uuid.uuid4(),
            knowledge_base_id=kb.id,
            title="doc",
            file_path="/x",
            file_type="md",
            file_size=1,
            status=status,
        )
        session.add(doc)
    await session.flush()
    created = []
    for ch in (chunks or []):
        cid = ch.get("chunk_id") or uuid.uuid4()
        session.add(
            Chunk(
                id=cid,
                document_id=doc.id,
                content=ch["content"],
                meta=ch.get("meta", {}),
                vector=ch.get("vector"),
            )
        )
        created.append(
            (str(cid), ch.get("meta", {}).get("title", ""), ch["content"], ch.get("meta", {}))
        )
    await session.flush()
    if created:
        # 回填: 写入 chunk_lexical_documents / chunk_lexical_terms
        await index_document_async(session, doc.id, str(kb.id), created)
    await session.commit()
    return tenant, kb, doc


# === 1. migration 建表 / downgrade ============================================
def test_migration_creates_and_drops_tables(pg_mig, monkeypatch):
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("ALEMBIC_DB_URL", pg_mig)
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))

    # upgrade: 建表
    command.upgrade(cfg, "head")
    with psycopg2.connect(pg_mig, connect_timeout=5) as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name IN ('chunk_lexical_documents','chunk_lexical_terms')"
        )
        n = cur.fetchone()[0]
    assert n == 2

    # downgrade: 删表(验证可执行 downgrade)
    command.downgrade(cfg, "base")
    with psycopg2.connect(pg_mig, connect_timeout=5) as c:
        cur = c.cursor()
        cur.execute(
            "SELECT count(*) FROM information_schema.tables "
            "WHERE table_name IN ('chunk_lexical_documents','chunk_lexical_terms')"
        )
        n = cur.fetchone()[0]
    assert n == 0


# === 2. 回填(index_document_async) ============================================
async def test_rebuild_populates_lexical_index(session):
    _, kb, doc = await _seed(
        session,
        chunks=[{"content": "RCS-931 差动保护 故障", "meta": {"model": "RCS-931"}}],
    )
    rows = (
        await session.execute(
            select(ChunkLexicalTerm).where(ChunkLexicalTerm.knowledge_base_id == kb.id)
        )
    ).scalars().all()
    assert len(rows) > 0
    terms = {r.term for r in rows}
    assert "rcs-931" in terms
    # document 行存在且 document_id 正确
    docs = (
        await session.execute(
            select(ChunkLexicalDocument).where(ChunkLexicalDocument.document_id == doc.id)
        )
    ).scalars().all()
    assert len(docs) == 1


# === 3. BM25 查询(向量为空时纯 BM25 命中) ====================================
async def test_bm25_query_returns_chunk(session):
    _, kb, _ = await _seed(
        session,
        chunks=[{"content": "RCS-931 差动保护装置 故障", "meta": {"model": "RCS-931"}}],
    )
    retriever = Retriever(session)
    results, timings = await retriever.similarity_search(
        query_vector=[0.0] * 512,
        kb_id=str(kb.id),
        top_k=5,
        threshold=0.0,
        query_text="差动保护",
        use_rerank=False,
        return_timings=True,
    )
    assert len(results) >= 1
    assert results[0].matched_channels == ["bm25"]
    assert results[0].bm25_score > 0
    assert timings["bm25_status"] == "ok"


# === 4. metadata / document_id 过滤(白名单, 防注入) ============================
async def test_filters_metadata_and_document_id(session):
    tenant = Tenant(id=uuid.uuid4(), name="t")
    session.add(tenant)
    kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb")
    session.add(kb)
    doc_a = Document(
        id=uuid.uuid4(), knowledge_base_id=kb.id, title="A",
        file_path="/a", file_type="md", file_size=1, status="ready",
    )
    doc_b = Document(
        id=uuid.uuid4(), knowledge_base_id=kb.id, title="B",
        file_path="/b", file_type="md", file_size=1, status="ready",
    )
    session.add_all([doc_a, doc_b])
    await session.flush()
    ca = Chunk(
        id=uuid.uuid4(),
        document_id=doc_a.id,
        content="RCS-931 差动保护",
        meta={"model": "RCS-931"},
        vector=None,
    )
    cb = Chunk(
        id=uuid.uuid4(),
        document_id=doc_b.id,
        content="PSL-621U 距离保护",
        meta={"model": "PSL-621U"},
        vector=None,
    )
    session.add_all([ca, cb])
    await session.flush()
    await index_document_async(
        session, doc_a.id, str(kb.id),
        [(str(ca.id), "A", "RCS-931 差动保护", {"model": "RCS-931"})],
    )
    await index_document_async(
        session, doc_b.id, str(kb.id),
        [(str(cb.id), "B", "PSL-621U 距离保护", {"model": "PSL-621U"})],
    )
    await session.commit()

    retriever = Retriever(session)

    # metadata 白名单过滤
    r1, _ = await retriever.similarity_search(
        [0.0] * 512, str(kb.id), 5, 0.0,
        filters={"model": "RCS-931"}, query_text="保护", use_rerank=False, return_timings=True,
    )
    assert {c.chunk_id for c in r1} == {str(ca.id)}

    # document_id 过滤
    r2, _ = await retriever.similarity_search(
        [0.0] * 512, str(kb.id), 5, 0.0,
        filters={"document_id": str(doc_a.id)},
        query_text="保护", use_rerank=False, return_timings=True,
    )
    assert {c.chunk_id for c in r2} == {str(ca.id)}

    # 无匹配
    r3, _ = await retriever.similarity_search(
        [0.0] * 512, str(kb.id), 5, 0.0,
        filters={"model": "NOPE"}, query_text="保护", use_rerank=False, return_timings=True,
    )
    assert r3 == []

    # 未知 filter key 被忽略(防注入): 返回全部, 不报错
    r4, _ = await retriever.similarity_search(
        [0.0] * 512, str(kb.id), 5, 0.0,
        filters={"author": "hacker'; DROP TABLE chunks; --"},
        query_text="保护", use_rerank=False, return_timings=True,
    )
    assert {c.chunk_id for c in r4} == {str(ca.id), str(cb.id)}

    # 恶意 value 被参数化绑定(不注入), 无匹配且不报错
    r5, _ = await retriever.similarity_search(
        [0.0] * 512, str(kb.id), 5, 0.0,
        filters={"model": "x'; DROP TABLE chunks; --"},
        query_text="保护", use_rerank=False, return_timings=True,
    )
    assert r5 == []


# === 5. Chunk / Document / KB 删除级联 ========================================
async def test_chunk_delete_cascade(session):
    _, kb, doc = await _seed(
        session,
        chunks=[
            {"content": "A 差动保护", "meta": {}},
            {"content": "B 距离保护", "meta": {}},
        ],
    )
    n = await ChunkRepositoryImpl(session).delete_by_document(doc.id)
    await session.commit()
    assert n == 2
    # chunks 与词法索引均被级联/显式清理
    assert (
        await session.execute(
            select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
        )
    ).scalar_one() == 0
    assert (
        await session.execute(
            select(func.count())
            .select_from(ChunkLexicalDocument)
            .where(ChunkLexicalDocument.document_id == doc.id)
        )
    ).scalar_one() == 0
    assert (
        await session.execute(
            select(func.count()).select_from(ChunkLexicalTerm)
            .join(ChunkLexicalDocument, ChunkLexicalDocument.chunk_id == ChunkLexicalTerm.chunk_id)
            .where(ChunkLexicalDocument.document_id == doc.id)
        )
    ).scalar_one() == 0


async def test_document_delete_cascade(session):
    _, kb, doc = await _seed(
        session, chunks=[{"content": "A 差动保护", "meta": {}}]
    )
    await DocumentRepositoryImpl(session).delete(doc.id)
    await session.commit()
    assert (
        await session.execute(
            select(func.count())
            .select_from(ChunkLexicalDocument)
            .where(ChunkLexicalDocument.knowledge_base_id == kb.id)
        )
    ).scalar_one() == 0


async def test_kb_delete_cascade(session):
    tenant, kb, doc = await _seed(
        session, chunks=[{"content": "A 差动保护", "meta": {}}]
    )
    await KnowledgeBaseRepositoryImpl(session).delete(kb.id, tenant.id)
    await session.commit()
    assert (
        await session.execute(
            select(func.count())
            .select_from(ChunkLexicalDocument)
            .where(ChunkLexicalDocument.knowledge_base_id == kb.id)
        )
    ).scalar_one() == 0


# === 6. batch_replace chunk_id 一致性 =========================================
async def test_batch_replace_uuid_consistency(session):
    tenant = Tenant(id=uuid.uuid4(), name="t")
    session.add(tenant)
    kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb")
    session.add(kb)
    doc = Document(
        id=uuid.uuid4(), knowledge_base_id=kb.id, title="doc",
        file_path="/x", file_type="md", file_size=1, status="ready",
    )
    session.add(doc)
    await session.flush()

    cid1 = str(uuid.uuid4())
    chunks = [
        {
            "chunk_id": cid1,
            "content": "RCS-931 差动保护",
            "meta": {"model": "RCS-931"},
        },
        # 不传 chunk_id -> 自动生成
        {"content": "PSL-621U 距离保护", "meta": {"model": "PSL-621U"}},
    ]
    await ChunkRepositoryImpl(session).batch_replace(doc.id, chunks)
    await session.commit()

    orm_ids = {
        str(c.id)
        for c in (
            await session.execute(select(Chunk).where(Chunk.document_id == doc.id))
        ).scalars().all()
    }
    assert cid1 in orm_ids
    # 词法索引 chunk_id 必须与 ORM 完全一致(复用同一 ID, 无差异)
    lex_ids = {
        str(r)
        for r in (
            await session.execute(
                select(ChunkLexicalDocument.chunk_id).where(
                    ChunkLexicalDocument.knowledge_base_id == kb.id
                )
            )
        ).scalars().all()
    }
    assert lex_ids == orm_ids
    assert len(lex_ids) == 2


# === 7. Embedding 失败后 BM25 单路降级 =======================================
async def test_embedding_failure_bm25_degrade(session, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(EmbeddingClient, "embed_single", AsyncMock(return_value=[]))
    _, kb, _ = await _seed(
        session, chunks=[{"content": "RCS-931 差动保护 故障", "meta": {}}]
    )
    retriever = Retriever(session)
    results, timings = await retriever.search(
        query_text="差动保护", kb_id=str(kb.id), top_k=5, use_rerank=False, return_timings=True
    )
    assert len(results) >= 1
    assert timings["vector_status"] == "error"
    assert timings["degraded_mode"] == "bm25_only"
    assert results[0].matched_channels == ["bm25"]


async def test_both_fail_returns_empty(session, monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(EmbeddingClient, "embed_single", AsyncMock(return_value=[]))
    # 让 BM25 也失败
    async def _boom(self, *a, **k):
        raise RuntimeError("bm25 down")

    monkeypatch.setattr(Retriever, "_bm25_search_sql", _boom)
    _, kb, _ = await _seed(
        session, chunks=[{"content": "RCS-931 差动保护", "meta": {}}]
    )
    retriever = Retriever(session)
    results, timings = await retriever.search(
        query_text="差动保护", kb_id=str(kb.id), top_k=5, use_rerank=False, return_timings=True
    )
    assert results == []
    assert timings["degraded_mode"] == "both_failed"
