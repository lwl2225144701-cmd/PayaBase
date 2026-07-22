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
    # 先终止该库所有连接(避免测试中断/连接泄漏导致 DROP 报 ObjectInUse)
    cur.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
        "WHERE datname = %s AND pid <> pg_backend_pid()",
        (name,),
    )
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
@pytest.mark.pg_integration
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
@pytest.mark.pg_integration
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
@pytest.mark.pg_integration
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
@pytest.mark.pg_integration
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
@pytest.mark.pg_integration
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


@pytest.mark.pg_integration
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


@pytest.mark.pg_integration
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
@pytest.mark.pg_integration
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
@pytest.mark.pg_integration
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


@pytest.mark.pg_integration
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


# === 8. Embedding 直接抛异常也降级(不只测返回 []) ==============================
@pytest.mark.pg_integration
async def test_embedding_exception_bm25_degrade(session, monkeypatch):
    async def _boom(self, *a, **k):
        raise RuntimeError("embedding service down")

    monkeypatch.setattr(EmbeddingClient, "embed_single", _boom)
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


# === 9. 旧库非级联外键 → migration 升级为级联 ================================
def _pg_fk(url, table, column, ref_table, ref_column):
    """返回 (约束名, delete_rule) 或 (None, None)。"""
    with psycopg2.connect(url, connect_timeout=5) as c:
        cur = c.cursor()
        cur.execute(
            """
            SELECT tc.constraint_name, rc.delete_rule
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
              ON tc.constraint_name = kcu.constraint_name
             AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = tc.constraint_name
             AND ccu.table_schema = tc.table_schema
            JOIN information_schema.referential_constraints rc
              ON rc.constraint_name = tc.constraint_name
             AND rc.constraint_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_name = %s
              AND kcu.column_name = %s
              AND ccu.table_name = %s
              AND ccu.column_name = %s
            """,
            (table, column, ref_table, ref_column),
        )
        row = cur.fetchone()
    return (row[0], row[1]) if row else (None, None)


def _verify_kb_cascade(url):
    """插入 tenant/kb/doc, 删 KB, 断言 document 被级联清理。

    用 SQLAlchemy Core 的表元数据插入: 列上的 Python 级 default
    (embedding_model / chunk_count / created_at / config 等) 会自动带入,
    无需手工补齐 NOT NULL 列。
    """
    from sqlalchemy import create_engine as _ce

    engine = _ce(url)
    tid = uuid.UUID("11111111-1111-1111-1111-111111111111")
    kid = uuid.UUID("22222222-2222-2222-2222-222222222222")
    did = uuid.UUID("33333333-3333-3333-3333-333333333333")
    with engine.begin() as conn:
        conn.execute(Tenant.__table__.insert().values(id=tid, name="t"))
        conn.execute(
            KnowledgeBase.__table__.insert().values(id=kid, tenant_id=tid, name="kb")
        )
        conn.execute(
            Document.__table__.insert().values(
                id=did,
                knowledge_base_id=kid,
                title="d",
                file_path="/x",
                file_type="md",
                file_size=1,
                status="ready",
            )
        )
        conn.execute(KnowledgeBase.__table__.delete().where(KnowledgeBase.__table__.c.id == kid))
        n = conn.execute(
            select(func.count()).select_from(Document).where(Document.__table__.c.id == did)
        ).scalar_one()
    engine.dispose()
    assert n == 0, "KB 删除未级联清理 documents(级联外键未生效)"


@pytest.fixture(scope="session")
def pg_mig_old():
    """模拟旧库: documents/chunks 外键为非级联(早期代码未带 ON DELETE CASCADE)。"""
    if not _pg_available():
        pytest.skip("本地 PostgreSQL 不可用, 跳过 migration 集成测试")
    name = "training_agent_test_mig_old"
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, name)
    admin.close()
    url = f"postgresql://training:training123@localhost:5432/{name}"
    sync = create_engine(url)
    with sync.connect() as c:
        c.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa_text("CREATE EXTENSION IF NOT EXISTS vector")
        )
    # 仅建父表(排除 chunk_lexical, 由 migration 创建)
    parent_tables = [
        t
        for t in Base.metadata.tables.values()
        if t.name not in ("chunk_lexical_documents", "chunk_lexical_terms")
    ]
    Base.metadata.create_all(sync, tables=parent_tables)
    # 把两个 FK 改为非级联, 模拟旧库(先 DROP 现有, 再以同名重建非级联)
    with sync.connect() as c:
        conn = c.execution_options(isolation_level="AUTOCOMMIT")
        for table, col, ref, refcol in [
            ("documents", "knowledge_base_id", "knowledge_bases", "id"),
            ("chunks", "document_id", "documents", "id"),
        ]:
            old, _ = _pg_fk(url, table, col, ref, refcol)
            if old:
                conn.execute(sa_text(f'ALTER TABLE {table} DROP CONSTRAINT "{old}"'))
            conn.execute(
                sa_text(
                    f'ALTER TABLE {table} ADD CONSTRAINT "{old}" '
                    f"FOREIGN KEY ({col}) REFERENCES {ref}({refcol})"
                )
            )
    yield url
    sync.dispose()
    admin = psycopg2.connect(ADMIN_SYNC, connect_timeout=5)
    _drop_and_create(admin, name)
    admin.close()


@pytest.mark.pg_integration
def test_migration_fixes_old_noncascade_fk(pg_mig_old, monkeypatch):
    from alembic import command
    from alembic.config import Config

    monkeypatch.setenv("ALEMBIC_DB_URL", pg_mig_old)
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))

    # 升级前: 非级联
    assert (
        _pg_fk(pg_mig_old, "documents", "knowledge_base_id", "knowledge_bases", "id")[1]
        == "NO ACTION"
    )
    assert (
        _pg_fk(pg_mig_old, "chunks", "document_id", "documents", "id")[1]
        == "NO ACTION"
    )

    # 升级到 head: 必须先把旧 FK DROP 再创建级联 FK
    command.upgrade(cfg, "head")
    assert (
        _pg_fk(pg_mig_old, "documents", "knowledge_base_id", "knowledge_bases", "id")[1]
        == "CASCADE"
    )
    assert (
        _pg_fk(pg_mig_old, "chunks", "document_id", "documents", "id")[1]
        == "CASCADE"
    )

    # 级联真实生效: 删 KB 连带文档被删
    _verify_kb_cascade(pg_mig_old)

    # 降回 base 可重复执行(还原为非级联)
    command.downgrade(cfg, "base")
    assert (
        _pg_fk(pg_mig_old, "documents", "knowledge_base_id", "knowledge_bases", "id")[1]
        == "NO ACTION"
    )


# === 10. 长文本 Chunk 两次回填第二次必须 skipped ==============================
@pytest.mark.pg_integration
async def test_rebuild_long_chunk_second_run_skipped(pg, session):
    from scripts.rebuild_lexical_index import process as rebuild_process

    # 构造超过 lexical_max_text_length 的长文本(触发截断)
    long_content = "继电保护装置定期检验规程要点与故障分析说明。" * 11112  # ≈200016 > 200000
    assert len(long_content) > settings.lexical_max_text_length

    tenant = Tenant(id=uuid.uuid4(), name="t")
    session.add(tenant)
    kb = KnowledgeBase(id=uuid.uuid4(), tenant_id=tenant.id, name="kb")
    session.add(kb)
    doc = Document(
        id=uuid.uuid4(), knowledge_base_id=kb.id, title="长文档",
        file_path="/x", file_type="md", file_size=1, status="ready",
    )
    session.add(doc)
    await session.flush()
    cid = uuid.uuid4()
    session.add(Chunk(id=cid, document_id=doc.id, content=long_content, meta={}))
    await session.commit()

    sync = pg["sync"]
    index_version = settings.lexical_index_version
    doc_dict = {"id": doc.id, "knowledge_base_id": kb.id, "title": doc.title}
    with sync.connect() as conn:
        klass1 = rebuild_process(conn, doc_dict, index_version, False, False)
        # 第一次写入后, 索引文本截断口径一致 → 第二次必须 skipped
        klass2 = rebuild_process(conn, doc_dict, index_version, False, False)
    assert klass1 in ("indexed", "updated")
    assert klass2 == "skipped"

