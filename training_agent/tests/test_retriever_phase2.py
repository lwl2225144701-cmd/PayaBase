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
    c0 = _make("c0", content="重复段落 内容 A")
    c1 = _make("c1", content="独有内容 B")
    c2 = _make("c2", content="重复段落 内容 A")  # 与 c0 同正文
    results, dedup_removed, doc_removed = _post_process_results(
        [c0, c1, c2], dedup=True, max_per_doc=0
    )
    assert len(results) == 2
    assert dedup_removed == 1
    assert doc_removed == 0
    assert {c.chunk_id for c in results} == {"c0", "c1"}  # 保留首条


def test_dedup_ignores_whitespace_and_case():
    c0 = _make("c0", content="  Hello   World  ")
    c1 = _make("c1", content="hello world")
    results, dedup_removed, _ = _post_process_results([c0, c1], dedup=True, max_per_doc=0)
    assert len(results) == 1
    assert dedup_removed == 1


def test_dedup_disabled_keeps_all():
    c0 = _make("c0", content="SAME")
    c1 = _make("c1", content="SAME")
    results, dedup_removed, _ = _post_process_results([c0, c1], dedup=False, max_per_doc=0)
    assert len(results) == 2
    assert dedup_removed == 0


# 4. 同文档结果数量限制 ----------------------------------------------------------
def test_max_results_per_doc_limits():
    chunks = [
        _make("c0", document_id="d1"),
        _make("c1", document_id="d1"),
        _make("c2", document_id="d1"),
        _make("c3", document_id="d1"),
        _make("c4", document_id="d2"),
    ]
    results, dedup_removed, doc_removed = _post_process_results(chunks, dedup=False, max_per_doc=2)
    assert dedup_removed == 0
    assert doc_removed == 2  # d1 的 4 条砍到 2, 移除 2
    assert len(results) == 3  # d1:2 + d2:1
    assert sum(1 for c in results if c.document_id == "d1") == 2


# 5. 组合: 先去重再文档限制, 顺序正确 --------------------------------------------
def test_dedup_then_doc_limit_order():
    chunks = [
        _make("a1", content="X", document_id="d1"),
        _make("a2", content="X", document_id="d1"),  # 与 a1 重复
        _make("a3", content="Y", document_id="d1"),
        _make("a4", content="Z", document_id="d1"),
        _make("b1", content="W", document_id="d2"),
        _make("b2", content="V", document_id="d2"),
    ]
    results, dedup_removed, doc_removed = _post_process_results(chunks, dedup=True, max_per_doc=2)
    # 去重: a1/a2 -> 1 条, 剩 5 条; 文档限制 d1<=2: 3条->2条 移除 1; 最终 4 条
    assert dedup_removed == 1
    assert doc_removed == 1
    assert len(results) == 4
    assert sum(1 for c in results if c.document_id == "d1") == 2
    assert sum(1 for c in results if c.document_id == "d2") == 2


# 6. 集成: similarity_search 应用 零分 BM25 剔除 + 去重 + 文档限制 --------------
async def test_similarity_search_applies_dedup_and_doc_limit():
    retriever = Retriever(db=MagicMock())
    # 6 行: d1 有 4 条(其中 c1/c2 正文相同), d2 有 2 条
    rows = [
        {"id": "c1", "content": "AAA", "summary": "AAA", "document_id": "d1", "meta": {},
         "title": "D1", "distance": 0.1},
        {"id": "c2", "content": "AAA", "summary": "AAA", "document_id": "d1", "meta": {},
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
    assert timings["dedup_removed_count"] == 1
    assert timings["doc_limit_removed_count"] == 1
    assert sum(1 for c in results if c.document_id == "d1") == 2
    # 排名连续重编号
    assert [c.final_rank for c in results] == [1, 2, 3, 4]
    # BM25 零分(doc 无 query 词重叠)的 bm25_rank 应为 None, 前端显示 "—"
    assert any(c.chunk_id == "c5" and c.bm25_rank is None for c in results)
