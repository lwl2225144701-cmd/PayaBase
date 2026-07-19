"""检索召回链路分数使用单元测试。

聚焦用户要求的 7 项验收:
1. rrf_score 不显示为相关度百分比, 不用于 threshold 过滤。
2. reranker 返回的 score 正确写回 chunk (rerank_score/final_score/score 一致, score_type=rerank)。
3. threshold 过滤生效 (0.92/0.71/0.49/0.21 @0.5 → 0.92/0.71)。
4. threshold 发生在最终 top_k 之前 (不足 top_k 按实际返回)。
5. 两个 content 完全相同但 chunk_id 不同的块, 必须按 index 正确映射, 不相互覆盖。
6. 全部低于 threshold 时返回空列表。
7. rerank 关闭时 score_type=rrf, 不执行 threshold, 不展示百分比。
"""

from unittest.mock import MagicMock, patch

from core.rag.ranker import Reranker, _sigmoid
from core.rag.retriever import RetrievedChunk, apply_rerank_scores, finalize_rrf


def _make(chunk_id, content="x", rrf_score=0.0, rrf_rank=1, document_id="d1"):
    return RetrievedChunk(
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


# 1. rrf_score 不显示为相关度百分比, 也不用于 threshold 过滤 --------------------------
def test_rrf_score_not_shown_as_relevance_and_not_thresholded():
    c = _make("c1", rrf_score=0.0328, rrf_rank=1)
    results = finalize_rrf([c], top_k=5)

    assert len(results) == 1
    # score 必须等于 rrf_score, 绝不能被当成百分比 (0.0328*100=3.28)
    assert results[0].score == 0.0328
    assert results[0].score != 0.0328 * 100
    assert results[0].final_score == 0.0328
    assert results[0].score_type == "rrf"
    # rrf 路径即使给出很高的 threshold 也不过滤
    assert len(finalize_rrf([c], top_k=5)) == 1


# 2. reranker score 正确写回 chunk ----------------------------------------------------
def test_rerank_score_written_back():
    c = _make("c1", rrf_score=0.01, rrf_rank=1)
    results = apply_rerank_scores([c], [(0, 0.91)], threshold=0.0, top_k=5)

    assert len(results) == 1
    r = results[0]
    assert r.rerank_score == 0.91
    assert r.final_score == 0.91
    assert r.score == 0.91
    assert r.score_type == "rerank"
    assert r.rerank_rank == 1
    assert r.final_rank == 1
    assert r.rank == 1


# 3. threshold 过滤生效 --------------------------------------------------------------
def test_threshold_filters_after_rerank():
    chunks = [_make(f"c{i}", rrf_rank=i + 1) for i in range(4)]
    pairs = [(0, 0.92), (1, 0.71), (2, 0.49), (3, 0.21)]
    results = apply_rerank_scores(chunks, pairs, threshold=0.5, top_k=10)

    assert [round(c.rerank_score, 2) for c in results] == [0.92, 0.71]


# 4. threshold 发生在最终 top_k 之前 (不足 top_k 按实际返回) -------------------------
def test_threshold_before_top_k():
    chunks = [_make(f"c{i}", rrf_rank=i + 1) for i in range(4)]
    pairs = [(0, 0.9), (1, 0.7), (2, 0.3), (3, 0.2)]
    # threshold 先过滤掉 0.3/0.2, 再截取 top_k=10 -> 只剩 2 条, 不会补满到 10
    results = apply_rerank_scores(chunks, pairs, threshold=0.5, top_k=10)
    assert [round(c.rerank_score, 2) for c in results] == [0.9, 0.7]


# 5. 相同 content 不同 chunk_id 必须按 index 正确映射 --------------------------------
def test_identical_content_distinct_mapping():
    c1 = _make("c1", content="SAME TEXT", rrf_rank=1)
    c2 = _make("c2", content="SAME TEXT", rrf_rank=2)
    chunks = [c1, c2]

    # 顺序映射
    apply_rerank_scores(chunks, [(0, 0.9), (1, 0.5)], threshold=0.0, top_k=5)
    assert c1.rerank_score == 0.9
    assert c2.rerank_score == 0.5

    # 逆序映射 (reranker 重排后顺序与输入不同)
    apply_rerank_scores(chunks, [(1, 0.9), (0, 0.5)], threshold=0.0, top_k=5)
    assert c2.rerank_score == 0.9
    assert c1.rerank_score == 0.5
    # 不相互覆盖
    assert c1.chunk_id == "c1" and c2.chunk_id == "c2"


# 6. 全部低于 threshold 时返回空列表 ------------------------------------------------
def test_all_below_threshold_empty():
    chunks = [_make(f"c{i}", rrf_rank=i + 1) for i in range(2)]
    pairs = [(0, 0.4), (1, 0.3)]
    results = apply_rerank_scores(chunks, pairs, threshold=0.5, top_k=5)
    assert results == []


# 7. rerank 关闭时 score_type=rrf, 不执行 threshold ---------------------------------
def test_rerank_off_no_threshold_no_percentage():
    c = _make("c1", rrf_score=0.0328, rrf_rank=1)
    results = finalize_rrf([c], top_k=5)
    assert len(results) == 1
    assert results[0].score_type == "rrf"
    assert results[0].score == 0.0328
    assert results[0].rerank_score is None


# 额外: 非法 score (None/NaN/Inf) 跳过, 不静默写成 0 --------------------------------
def test_invalid_rerank_score_skipped():
    c0 = _make("c0", rrf_rank=1)
    c1 = _make("c1", rrf_rank=2)
    c2 = _make("c2", rrf_rank=3)
    pairs = [(0, float("nan")), (1, 0.8), (2, float("inf"))]
    results = apply_rerank_scores([c0, c1, c2], pairs, threshold=0.0, top_k=5)

    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert results[0].rerank_score == 0.8


# 额外: Reranker 返回 index (非 content) 且归一化到 [0,1] ---------------------------
def test_reranker_returns_index_not_content():
    fake_response = MagicMock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {"results": [1, 0], "scores": [2.0, -1.0]}

    fake_client = MagicMock()
    fake_client.__enter__.return_value = fake_client
    fake_client.__exit__.return_value = False
    fake_client.post.return_value = fake_response

    with patch("core.rag.ranker.httpx.Client", return_value=fake_client):
        reranker = Reranker(base_url="http://fake")
        out = reranker.rerank("q", [{"content": "a"}, {"content": "b"}], 2, False)

    assert out == [
        {"index": 1, "rerank_score": _sigmoid(2.0)},
        {"index": 0, "rerank_score": _sigmoid(-1.0)},
    ]
    # 归一化后落在 (0,1)
    assert 0 < out[0]["rerank_score"] < 1
    assert 0 < out[1]["rerank_score"] < 1
    # index 顺序与 content 顺序不同 -> 证明是按 index 映射, 非 content
    assert out[0]["index"] == 1


def test_sigmoid_monotonic_and_bounded():
    assert _sigmoid(0) == 0.5
    assert _sigmoid(100) > 0.99
    assert _sigmoid(-100) < 0.01
    assert _sigmoid(2.0) > _sigmoid(-1.0)
