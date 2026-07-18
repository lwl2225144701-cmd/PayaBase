"""领域实体（aggregates）映射与不变量测试（Phase 4）。

用 types.SimpleNamespace 模拟 ORM 行，验证 from_orm 映射准确、
业务不变量方法（状态机 / 进度推导 / 重索引判定）行为正确。
"""
from types import SimpleNamespace
from uuid import uuid4

from core.domain.agent.aggregates import AgentRun, AgentRunStatus, AgentStep
from core.domain.conversation.aggregates import Conversation, Message
from core.domain.identity.aggregates import User
from core.domain.knowledge_base.aggregates import (
    Chunk,
    Document,
    DocumentStatus,
    KnowledgeBase,
)


def _doc_orm(status: str, chunk_count: int = 0, progress: int = 0, error: str | None = None):
    return SimpleNamespace(
        id=uuid4(),
        knowledge_base_id=uuid4(),
        title="t",
        file_path="p",
        file_type="pdf",
        file_size=10,
        status=status,
        chunk_count=chunk_count,
        progress=progress,
        file_hash="h",
        source_type="local",
        source_url=None,
        error_message=error,
        indexed_at=None,
        created_at=None,
    )


def test_document_ready_invariants():
    d = Document.from_orm(_doc_orm("ready", chunk_count=5, progress=100))
    assert d.is_indexed()
    assert not d.is_indexing()
    assert not d.is_failed()
    assert d.can_reindex()  # ready 可重索引
    assert d.derive_progress() == 100
    assert d.mark_ready(7)["progress"] == 100
    assert d.mark_ready(7)["status"] == DocumentStatus.READY


def test_document_indexing_progress_and_no_reindex():
    d = Document.from_orm(_doc_orm("indexing", chunk_count=5, progress=0))
    assert d.is_indexing()
    assert d.derive_progress() == 50  # min(5*10, 90)
    assert not d.can_reindex()  # 进行中不可重索引


def test_document_error_can_reindex():
    d = Document.from_orm(_doc_orm("error", error="boom"))
    assert d.is_failed()
    assert d.can_reindex()  # error 允许重试
    upd = d.mark_failed("x")
    assert upd["status"] == DocumentStatus.ERROR
    assert upd["error_message"] == "x"


def test_document_pending_is_indexing():
    d = Document.from_orm(_doc_orm("pending"))
    assert d.is_indexing()  # pending 同属「索引中」
    assert not d.is_indexed()


def test_chunk_knowledgebase_from_orm():
    chunk_orm = SimpleNamespace(
        id=uuid4(), document_id=uuid4(), content="c", chunk_type="recursive",
        token_count=3, summary=None, meta={"k": 1},
    )
    c = Chunk.from_orm(chunk_orm)
    assert c.content == "c"
    assert c.token_count == 3
    assert c.meta == {"k": 1}

    kb_orm = SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), name="kb", embedding_model="m",
        description=None, created_at=None,
    )
    kb = KnowledgeBase.from_orm(kb_orm)
    assert kb.name == "kb"
    assert kb.embedding_model == "m"


def test_conversation_message_invariants():
    conv = Conversation.from_orm(SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), user_id=uuid4(), title="c",
        knowledge_base_id=None, meta={}, created_at=None,
    ))
    assert not conv.belongs_to_kb(uuid4())

    msg = Message.from_orm(SimpleNamespace(
        id=uuid4(), conversation_id=uuid4(), role="user", content="hi",
        token_count=3, latency_ms=1, context={}, citations=[], created_at=None,
    ))
    assert msg.is_user()
    assert not msg.is_assistant()

    msg_a = Message.from_orm(SimpleNamespace(
        id=uuid4(), conversation_id=uuid4(), role="assistant", content="ok",
        token_count=5, latency_ms=2, context={}, citations=[], created_at=None,
    ))
    assert msg_a.is_assistant()


def test_agent_run_invariants():
    run = AgentRun.from_orm(SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), user_id=uuid4(), conversation_id=uuid4(),
        goal="g", status="running", route=None, current_step=None, next_step=None,
        completed_steps_summary="", plan_snapshot={}, step_history=[], artifacts=[],
        last_error=None, retry_count=0, budget_remaining=0,
        created_at=None, updated_at=None, completed_at=None,
    ))
    assert run.is_running()
    assert not run.is_terminal()
    assert not run.is_failed()

    run.status = AgentRunStatus.COMPLETED
    assert run.is_terminal()

    run.status = AgentRunStatus.FAILED
    assert run.is_terminal()
    assert run.is_failed()


def test_agent_step_invariants():
    step = AgentStep.from_orm(SimpleNamespace(
        id=uuid4(), run_id=uuid4(), step_key="k", step_type="t", step_goal="g",
        status="failed", output="", error="e", tool_trace=[], created_at=None, updated_at=None,
    ))
    assert step.is_failed()
    assert not step.is_completed()
    assert not step.is_pending()


def test_user_is_admin():
    u = User.from_orm(SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), name="n", email="e", role="admin",
        department_id=None, hr_user_id=None, sso_id=None,
    ))
    assert u.is_admin()

    u2 = User.from_orm(SimpleNamespace(
        id=uuid4(), tenant_id=uuid4(), name="n", email="e", role="user",
        department_id=None, hr_user_id=None, sso_id=None,
    ))
    assert not u2.is_admin()
