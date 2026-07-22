"""第四阶段 — 纯逻辑单元测试(不触网、不连库)。

覆盖:
- build_context_blocks_for_document 父块生成规则(4~8 子块 / token 范围 / 连续 sequence_no)
- 章节边界优先分开
- assemble_context_groups 合并(同父块单组 / 相邻窗口重叠合并 / 跨文档不合并 / 按 rank 排序)
- 整次预算截断
- expand_results 关闭时保留 final_score/final_rank
- rebuild _needs_rebuild 幂等(skipped)
"""
from unittest.mock import AsyncMock

from core.rag.context_blocks import build_context_blocks_for_document
from core.rag.context_expansion import assemble_context_groups, expand_results
from core.rag.retriever import RetrievedChunk


def _mk(
    chunk_id,
    doc_id="d1",
    seq=0,
    final_rank=1,
    content="x",
    parent_id=None,
    context_content=None,
    context_source=None,
    score=0.5,
):
    c = RetrievedChunk(
        chunk_id=chunk_id,
        content=content,
        document_id=doc_id,
        document_title="T",
        score=score,
        metadata={},
        final_rank=final_rank,
    )
    c.sequence_no = seq
    c.parent_context_id = parent_id
    c.context_content = context_content
    c.context_source = context_source
    c.context_char_count = len(context_content or "")
    c.context_truncated = False
    return c


# === 一、父块生成规则 =========================================================
def test_build_context_blocks_parent_range_and_sequence():
    # 20 个子块, 每块约 133 tokens(默认 target=1400 但 max_children=8 限制)
    chunks = [{"content": "块内容" * 60, "meta": {}, "token_count": 133} for _ in range(20)]
    updated, blocks = build_context_blocks_for_document("doc-1", chunks)

    # sequence_no 连续 0..19
    assert [c["sequence_no"] for c in updated] == list(range(20))

    # 父块数量: 20/8 → 3 个(8,8,4)
    assert 3 <= len(blocks) <= 5

    # 每个父块子块数 4~8
    for b in blocks:
        n = b["end_sequence"] - b["start_sequence"] + 1
        assert 4 <= n <= 8

    # 父块覆盖全部子块, 无重叠无遗漏
    covered = set()
    for b in blocks:
        covered.update(range(b["start_sequence"], b["end_sequence"] + 1))
    assert covered == set(range(20))

    # 同一文档内连续(不跨文档)
    for b in blocks:
        assert b["document_id"] == "doc-1"

    # 子块关联到父块(前 8 个属于第一个父块)
    assert updated[0]["context_block_id"] == blocks[0]["id"]
    assert updated[7]["context_block_id"] == blocks[0]["id"]
    assert updated[8]["context_block_id"] == blocks[1]["id"]


def test_build_context_blocks_respects_heading_boundary():
    # 第 5 块是章节标题, 应作为分界起点(强制分开)
    chunks = []
    for i in range(12):
        if i == 5:
            chunks.append(
                {"content": "## 新章节标题", "meta": {"is_heading": True}, "token_count": 10}
            )
        else:
            chunks.append({"content": f"正文{i}" * 30, "meta": {}, "token_count": 100})
    updated, blocks = build_context_blocks_for_document("doc-2", chunks)

    # 第 5 块(章节边界)不应与前面同一父块
    bid_before = updated[4]["context_block_id"]
    bid_at = updated[5]["context_block_id"]
    assert bid_before != bid_at, "章节边界应优先分开父块"


def test_build_context_blocks_no_cross_document():
    # build 只接收单个文档的 chunks, 天然不跨文档
    chunks = [{"content": f"c{i}", "meta": {}, "token_count": 50} for i in range(10)]
    _, blocks = build_context_blocks_for_document("doc-A", chunks)
    assert all(b["document_id"] == "doc-A" for b in blocks)


# === 二、上下文组合并 =========================================================
def test_assemble_same_parent_single_group():
    # 两个命中子块属于同一父块 → 只生成一个上下文组
    c1 = _mk("c1", seq=1, final_rank=1, parent_id="pb1", context_content="父块内容AAAA")
    c2 = _mk("c2", seq=2, final_rank=2, parent_id="pb1", context_content="父块内容AAAA")
    groups = assemble_context_groups([c1, c2])
    assert len(groups) == 1
    g = groups[0]
    assert g.parent_context_id == "pb1"
    assert set(g.child_chunk_ids) == {"c1", "c2"}
    assert "AAAA" in g.context_content


def test_assemble_overlap_windows_merge():
    # 两个无父块子块相邻窗口重叠 → 合并为一组(不重复内容)
    c1 = _mk("c1", seq=5, final_rank=1, context_content="共同相邻内容XYZ")
    c2 = _mk("c2", seq=6, final_rank=2, context_content="共同相邻内容XYZ")
    groups = assemble_context_groups([c1, c2])
    assert len(groups) == 1
    assert set(groups[0].child_chunk_ids) == {"c1", "c2"}


def test_assemble_cross_doc_not_merged():
    c1 = _mk("c1", doc_id="d1", seq=1, final_rank=1, context_content="AAA")
    c2 = _mk("c2", doc_id="d2", seq=1, final_rank=2, context_content="BBB")
    groups = assemble_context_groups([c1, c2])
    assert len(groups) == 2
    assert all(g.document_id in ("d1", "d2") for g in groups)


def test_assemble_sorted_by_min_final_rank():
    # seq 间隔大(10 vs 1), 相邻窗口不重叠 → 两组, 按 min_final_rank 排序
    c_high = _mk("ch", seq=10, final_rank=5, context_content="低优先级")
    c_low = _mk("cl", seq=1, final_rank=1, context_content="高优先级")
    groups = assemble_context_groups([c_high, c_low])
    assert len(groups) == 2
    assert groups[0].min_final_rank == 1
    assert groups[1].min_final_rank == 5


def test_assemble_total_budget_truncates_far_groups():
    # 制造超长上下文, 触发整次预算 24000 截断
    big = "内容" * 5000  # ~10000 字符
    members = [
        _mk(f"c{i}", seq=i, final_rank=i + 1, context_content=big) for i in range(6)
    ]
    groups = assemble_context_groups(members)
    total = sum(g.context_char_count for g in groups)
    # 6 * 10000 = 60000 > 24000, 应被截断
    assert total <= 24000
    # 至少一组被标记截断
    assert any(g.context_truncated for g in groups)


# === 三、expand_results 关闭时行为 ===========================================
async def test_expand_disabled_keeps_scores_and_ranks(monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "context_expansion_enabled", False)
    results = [
        _mk("c1", seq=1, final_rank=1, score=0.9),
        _mk("c2", seq=2, final_rank=2, score=0.8),
    ]
    db = AsyncMock()
    out, stats = await expand_results(db, results)
    # 不查 DB, 原样返回
    assert out is results
    assert stats["context_expansion_enabled"] is False
    # final_score / final_rank 不变
    assert results[0].final_rank == 1 and results[0].score == 0.9
    assert results[1].final_rank == 2 and results[1].score == 0.8


def test_expand_disabled_falls_back_to_child_content(monkeypatch):
    """关闭扩展时, assemble 应使用 child.content 作为上下文(与第三阶段一致)。"""
    from core.config import settings

    monkeypatch.setattr(settings, "context_expansion_enabled", False)
    c1 = _mk("c1", seq=1, final_rank=1, content="子块原文A", context_content=None)
    c2 = _mk("c2", seq=2, final_rank=2, content="子块原文B", context_content=None)
    groups = assemble_context_groups([c1, c2])
    # context_content 为 None 时 fallback 到 child.content, 不报错
    joined = " ".join(g.context_content for g in groups)
    assert "子块原文A" in joined
    assert "子块原文B" in joined
