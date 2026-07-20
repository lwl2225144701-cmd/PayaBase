"""第二阶段检索优化单元测试:

1. 标准 RRF: 仅用排名(rank), 与原始 score 无关; 多路排名倒数求和。
2. BM25 零分结果不参与 RRF 融合。
3. 重复切片去重: 同正文(归一化后)只保留首条。
4. 同文档结果数量限制: 可配置, 超出部分移除。
5. 组合: 先去重再文档限制, 顺序正确。
6. 集成: similarity_search 端到端应用 零分 BM25 剔除 + 去重 + 文档限制
   (rerank 关闭路径, 用 mock DB, 不触网)。
"""

from unittest.mock import AsyncMock, MagicMock, patch

from core.config import settings
from core.rag.retriever import (
    RetrievedChunk,
    Retriever,
    _filter_valid_bm25_results,
    _post_process_results,
)


def _make(chunk_id, content="x", rrf_score=0.0, rrf_rank=1, document_id="d1", rerank_score=None):
    c = RetrievedChunk(
        chunk_id=chunk_id,
        content=content,
        document_id=document_id,
        document_title="t",
        score=float(rrf_score),
        metadata={},
        rank=rrf_rank,
        rrf_score=float(rrf_score),
        rrf_rank=rrf_rank,
    )
    if rerank_score is not None:
        c.rerank_score = rerank_score
        c.score_type = "rerank"
    return c


# 1. 标准 RRF 只用排名, 不受原始 score 取值影响 -----------------------------------
def test_standard_rrf_uses_rank_not_score():
    r = Retriever(db=None)
    k = 60
    # 两组 score 取值完全不同, 但排名相同 -> 融合分必须完全一致
    group_a = [(0, 0.99), (1, 0.01)]   # 高/低 sim
    group_b = [(0, 0.001), (1, 0.999)] # 低/高 sim
    fusion_a = dict(r._rrf_fusion(group_a, [], k=k))
    fusion_b = dict(r._rrf_fusion(group_b, [], k=k))
    assert abs(fusion_a[0] - fusion_b[0]) < 1e-12
    assert abs(fusion_a[1] - fusion_b[1]) < 1e-12
    # 排名 1 -> 1/(k+1), 排名 2 -> 1/(k+2)
    assert abs(fusion_a[0] - 1.0 / (k + 1)) < 1e-12
    assert abs(fusion_a[1] - 1.0 / (k + 2)) < 1e-12


def test_standard_rrf_vector_and_bm25_reciprocal_sum():
    r = Retriever(db=None)
    k = 60
    vector_results = [(0, 0.9), (1, 0.1)]
    bm25_results = [(0, 0.8), (1, 0.2)]
    fusion = dict(r._rrf_fusion(vector_results, bm25_results, k=k))
    # doc0 在两路均 rank1 -> 2/(k+1); doc1 均 rank2 -> 2/(k+2)
    assert abs(fusion[0] - 2.0 / (k + 1)) < 1e-12
    assert abs(fusion[1] - 2.0 / (k + 2)) < 1e-12


# 2. BM25 零分结果不参与融合 -----------------------------------------------------
def test_bm25_zero_score_excluded_from_fusion():
    bm25 = [(0, 0.0), (1, 0.5), (2, 0.3)]
    valid = _filter_valid_bm25_results(bm25)
    assert valid == [(1, 0.5), (2, 0.3)]
    r = Retriever(db=None)
    fusion = dict(r._rrf_fusion([], valid, k=60))
    assert 0 not in fusion  # 零分 doc 未进入融合
    assert 1 in fusion and 2 in fusion


def test_bm25_only_strictly_positive_participates():
    # 仅严格 >0 才参与, 0 与负值均剔除
    assert _filter_valid_bm25_results([(0, 0.0), (1, -0.1)]) == []


# 3. 重复切片去重 ----------------------------------------------------------------
def test_dedup_removes_duplicate_content():
    # 长正文(>50)才走「正文归一化去重」, 短文本只按 chunk_id
    dup_a = "长文本重复段落内容A用于验证正文去重逻辑在此测试用例中生效并保持首条" * 2
    c0 = _make("c0", content=dup_a)
    c1 = _make("c1", content="长文本独有内容B用于验证不同正文不会被误删保留其本身" * 2)
    c2 = _make("c2", content=dup_a)  # 与 c0 同正文
    results, stats = _post_process_results([c0, c1, c2], dedup=True, max_per_doc=0)
    assert len(results) == 2
    assert stats["deduplicate_removed_count"] == 1
    assert stats["document_limit_removed_count"] == 0
    assert {c.chunk_id for c in results} == {"c0", "c1"}  # 保留首条


def test_dedup_ignores_whitespace_and_case():
    base = ("Hello   World 这是一段用于验证大小写与空白归一化去重的长文本测试用例" * 2)
    c0 = _make("c0", content="  " + base + "  ")
    c1 = _make("c1", content=base.lower())
    results, stats = _post_process_results([c0, c1], dedup=True, max_per_doc=0)
    assert len(results) == 1
    assert stats["deduplicate_removed_count"] == 1


def test_dedup_disabled_keeps_all():
    c0 = _make("c0", content="SAME")
    c1 = _make("c1", content="SAME")
    results, stats = _post_process_results([c0, c1], dedup=False, max_per_doc=0)
    assert len(results) == 2
    assert stats["deduplicate_removed_count"] == 0


# 4. 同文档结果数量限制 ----------------------------------------------------------
def test_max_results_per_doc_limits():
    chunks = [
        _make("c0", document_id="d1"),
        _make("c1", document_id="d1"),
        _make("c2", document_id="d1"),
        _make("c3", document_id="d1"),
        _make("c4", document_id="d2"),
    ]
    results, stats = _post_process_results(chunks, dedup=False, max_per_doc=2)
    assert stats["deduplicate_removed_count"] == 0
    assert stats["document_limit_removed_count"] == 2  # d1 的 4 条砍到 2, 移除 2
    assert len(results) == 3  # d1:2 + d2:1
    assert sum(1 for c in results if c.document_id == "d1") == 2


# 5. 组合: 先去重再文档限制, 顺序正确 --------------------------------------------
def test_dedup_then_doc_limit_order():
    dup_x = "长文本X用于验证去重此块与另一块同正文应被合并只留首条" * 2
    chunks = [
        _make("a1", content=dup_x, document_id="d1"),
        _make("a2", content=dup_x, document_id="d1"),  # 与 a1 同正文(重复)
        _make("a3", content="长文本Y用于验证不同正文保留" * 2, document_id="d1"),
        _make("a4", content="长文本Z用于验证不同正文保留" * 2, document_id="d1"),
        _make("b1", content="长文本W用于验证不同文档" * 2, document_id="d2"),
        _make("b2", content="长文本V用于验证不同文档" * 2, document_id="d2"),
    ]
    results, stats = _post_process_results(chunks, dedup=True, max_per_doc=2)
    # 去重: a1/a2 -> 1 条, 剩 5 条; 文档限制 d1<=2: 3条->2条 移除 1; 最终 4 条
    assert stats["deduplicate_removed_count"] == 1
    assert stats["document_limit_removed_count"] == 1
    assert len(results) == 4
    assert sum(1 for c in results if c.document_id == "d1") == 2
    assert sum(1 for c in results if c.document_id == "d2") == 2


# 6. 集成: similarity_search 应用 零分 BM25 剔除 + 去重 + 文档限制 --------------
async def test_similarity_search_applies_dedup_and_doc_limit():
    retriever = Retriever(db=MagicMock())
    # 长重复正文(>50 字符), 确保走「正文归一化去重」而非短文本按 chunk_id 路径
    dup_long = "文档检索优化第二阶段去重测试用的长重复正文内容用于验证切片去重优先于top_k截取" * 2
    # 6 行: d1 有 4 条(其中 c1/c2 正文相同), d2 有 2 条
    rows = [
        {"id": "c1", "content": dup_long, "summary": dup_long, "document_id": "d1", "meta": {},
         "title": "D1", "distance": 0.1},
        {"id": "c2", "content": dup_long, "summary": dup_long, "document_id": "d1", "meta": {},
         "title": "D1", "distance": 0.2},
        {"id": "c3", "content": "BBB", "summary": "BBB", "document_id": "d1", "meta": {},
         "title": "D1", "distance": 0.3},
        {"id": "c4", "content": "CCC", "summary": "CCC", "document_id": "d1", "meta": {},
         "title": "D1", "distance": 0.4},
        {"id": "c5", "content": "DDD", "summary": "DDD", "document_id": "d2", "meta": {},
         "title": "D2", "distance": 0.5},
        {"id": "c6", "content": "EEE", "summary": "EEE", "document_id": "d2", "meta": {},
         "title": "D2", "distance": 0.6},
    ]
    fake_result = MagicMock()
    fake_result.mappings().all.return_value = rows
    retriever.db.execute = AsyncMock(return_value=fake_result)

    with patch.object(settings, "max_results_per_doc", 2), patch.object(
        settings, "rerank_override", "off"
    ):
        results, timings = await retriever.similarity_search(
            query_vector=[0.0] * 512,
            kb_id="00000000-0000-0000-0000-000000000000",
            top_k=10,
            threshold=0.0,
            query_text="aaa bbb",
            use_rerank=False,
            return_timings=True,
        )

    # 去重 c1/c2 (同正文) -> 移除 1; 文档限制 d1<=2 -> 移除 1; 最终 4 条
    assert len(results) == 4
    assert timings["deduplicate_removed_count"] == 1
    assert timings["document_limit_removed_count"] == 1
    assert sum(1 for c in results if c.document_id == "d1") == 2
    # 排名连续重编号
    assert [c.final_rank for c in results] == [1, 2, 3, 4]
    # BM25 零分(doc 无 query 词重叠)的 bm25_rank 应为 None, 前端显示 "—"
    assert any(c.chunk_id == "c5" and c.bm25_rank is None for c in results)


# 7. 短文本(< min_content_length)只按 chunk_id 去重, 不参与正文归一化匹配 --------
def test_short_text_dedup_only_by_chunk_id():
    # 两短文本正文相同但 chunk_id 不同 -> 不按正文合并, 都保留
    c0 = _make("c0", content="SAME")
    c1 = _make("c1", content="SAME")
    results, stats = _post_process_results([c0, c1], dedup=True, max_per_doc=0)
    assert len(results) == 2
    assert stats["deduplicate_removed_count"] == 0


# 8. 内容去重发生在 final top_k 之前 ---------------------------------------------
def test_dedup_happens_before_top_k():
    # 8 条有序结果(按 final_rank 1..8); 前 3 条正文相同(长文本, 走正文去重)
    dup = "这是一段足够长的重复正文内容用于验证去重发生在 top_k 截取之前再取最终 Top5" * 2
    chunks = [
        _make("c1", content=dup, rrf_rank=1),
        _make("c2", content=dup, rrf_rank=2),  # 与 c1 同正文 -> 重复
        _make("c3", content=dup, rrf_rank=3),  # 与 c1 同正文 -> 重复
        _make("c4", content="独有内容 D 第四名", rrf_rank=4),
        _make("c5", content="独有内容 E 第五名", rrf_rank=5),
        _make("c6", content="独有内容 F 第六名", rrf_rank=6),
        _make("c7", content="独有内容 G 第七名", rrf_rank=7),
        _make("c8", content="独有内容 H 第八名", rrf_rank=8),
    ]
    # 若去重发生在 top_k 之后: top_k=5 取 c1..c5 -> c2/c3 与 c1 重复 ->
    #   去重后仅 3 条, 无法凑满 Top5。
    # 正确(去重先于 top_k): 去重 c2/c3 -> 剩 [c1,c4,c5,c6,c7,c8] -> top_k=5 -> 5 条。
    results, stats = _post_process_results(chunks, dedup=True, max_per_doc=0, top_k=5)
    assert len(results) == 5  # 完整 Top5, 证明去重先于 top_k
    assert stats["deduplicate_removed_count"] == 2
    ids = {c.chunk_id for c in results}
    assert "c1" in ids  # 重复组保留首条
    assert "c6" in ids and "c7" in ids  # 原本排第 6/7 的也进入 Top5


# 9. 同文档限制默认 3; 候选仅含一个有效 document_id 时自动跳过 -------------------
def test_max_results_per_doc_limits_to_three_with_multi_doc():
    # 多文档场景下, 每个文档最多保留 3 条(对应配置默认 3)
    chunks = [
        _make(f"c{i}", document_id="d1") for i in range(4)
    ] + [
        _make(f"e{i}", document_id="d2") for i in range(2)
    ]
    results, stats = _post_process_results(chunks, dedup=False, max_per_doc=3)
    assert stats["document_limit_enabled"] is True
    assert len(results) == 5  # d1:3 + d2:2
    assert sum(1 for c in results if c.document_id == "d1") == 3
    assert sum(1 for c in results if c.document_id == "d2") == 2


def test_single_valid_doc_skips_limit():
    # 全部来自同一 document_id, 即使超过 max_per_doc 也不限制
    chunks = [_make(f"c{i}", document_id="d1") for i in range(5)]
    results, stats = _post_process_results(chunks, dedup=False, max_per_doc=3)
    assert stats["document_limit_enabled"] is False
    assert len(results) == 5  # 未限制


# 10. document_id 为空时使用 unknown:{chunk_id}, 避免空 ID 被并为一文档 -----------
def test_empty_document_id_treated_as_distinct():
    c0 = _make("c0", document_id="")
    c1 = _make("c1", document_id="")
    # 两个空 document_id -> 两个有效 doc(各自 unknown:chunk_id) -> 限制启用且各自保留
    results, stats = _post_process_results([c0, c1], dedup=False, max_per_doc=1)
    assert stats["document_limit_enabled"] is True
    assert len(results) == 2  # 未因空 ID 误合并
