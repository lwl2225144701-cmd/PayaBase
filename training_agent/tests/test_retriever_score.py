"""检索召回链路分数使用单元测试。

聚焦用户要求的 7 项验收:
1. rrf_score 不显示为相关度百分比, 不用于 threshold 过滤。
2. reranker 返回的 score 正确写回 chunk (rerank_score/final_score/score 一致, score_type=rerank)。
3. threshold 过滤生效 (0.92/0.71/0.49/0.21 @0.5 → 0.92/0.71)。
4. threshold 发生在最终 top_k 之前 (不足 top_k 按实际返回)。
5. 两个 content 完全相同但 chunk_id 不同的块, 必须按 index 正确映射, 不相互覆盖。
6. 全部低于 threshold 时返回空列表。
7. rerank 关闭时 score_type=rrf, 不执行 threshold, 不展示百分比。

补充(本轮):
8. actual_candidate_k 不得受 final top_k 限制 —— RRF 候选全集(受 rerank_candidate_k 上限约束)
   进入 rerank, 而非被 top_k 截断。
9. 完整链路: RRF 前 20 条 → 全部经过 Rerank → threshold 过滤 → 最终取 Top5;
   threshold_passed_count 统计 top_k 截取前的通过数。
"""

from unittest.mock import MagicMock, patch

from core.config import settings
from core.rag.ranker import Reranker, _sigmoid
from core.rag.retriever import (
    RetrievedChunk,
    Retriever,
    _post_process_results,
    apply_rerank_scores,
    finalize_rrf,
)


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
    results = finalize_rrf([c])

    assert len(results) == 1
    # score 必须等于 rrf_score, 绝不能被当成百分比 (0.0328*100=3.28)
    assert results[0].score == 0.0328
    assert results[0].score != 0.0328 * 100
    assert results[0].final_score == 0.0328
    assert results[0].score_type == "rrf"
    # rrf 路径即使给出很高的 threshold 也不过滤
    assert len(finalize_rrf([c])) == 1


# 2. reranker score 正确写回 chunk ----------------------------------------------------
def test_rerank_score_written_back():
    c = _make("c1", rrf_score=0.01, rrf_rank=1)
    results = apply_rerank_scores([c], [(0, 0.91)], threshold=0.0)

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
    results = apply_rerank_scores(chunks, pairs, threshold=0.5)

    assert [round(c.rerank_score, 2) for c in results] == [0.92, 0.71]


# 4. threshold 发生在最终 top_k 之前 (不足 top_k 按实际返回) -------------------------
def test_threshold_before_top_k():
    chunks = [_make(f"c{i}", rrf_rank=i + 1) for i in range(4)]
    pairs = [(0, 0.9), (1, 0.7), (2, 0.3), (3, 0.2)]
    # threshold 先过滤掉 0.3/0.2, 再截取 top_k=10 -> 只剩 2 条, 不会补满到 10
    results = apply_rerank_scores(chunks, pairs, threshold=0.5)
    assert [round(c.rerank_score, 2) for c in results] == [0.9, 0.7]


# 5. 相同 content 不同 chunk_id 必须按 index 正确映射 --------------------------------
def test_identical_content_distinct_mapping():
    c1 = _make("c1", content="SAME TEXT", rrf_rank=1)
    c2 = _make("c2", content="SAME TEXT", rrf_rank=2)
    chunks = [c1, c2]

    # 顺序映射
    apply_rerank_scores(chunks, [(0, 0.9), (1, 0.5)], threshold=0.0)
    assert c1.rerank_score == 0.9
    assert c2.rerank_score == 0.5

    # 逆序映射 (reranker 重排后顺序与输入不同)
    apply_rerank_scores(chunks, [(1, 0.9), (0, 0.5)], threshold=0.0)
    assert c2.rerank_score == 0.9
    assert c1.rerank_score == 0.5
    # 不相互覆盖
    assert c1.chunk_id == "c1" and c2.chunk_id == "c2"


# 6. 全部低于 threshold 时返回空列表 ------------------------------------------------
def test_all_below_threshold_empty():
    chunks = [_make(f"c{i}", rrf_rank=i + 1) for i in range(2)]
    pairs = [(0, 0.4), (1, 0.3)]
    results = apply_rerank_scores(chunks, pairs, threshold=0.5)
    assert results == []


# 7. rerank 关闭时 score_type=rrf, 不执行 threshold ---------------------------------
def test_rerank_off_no_threshold_no_percentage():
    c = _make("c1", rrf_score=0.0328, rrf_rank=1)
    results = finalize_rrf([c])
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
    results = apply_rerank_scores([c0, c1, c2], pairs, threshold=0.0)

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


# 8. actual_candidate_k 不得受 final top_k 限制 --------------------------------------
def test_rrf_candidate_k_not_limited_by_top_k():
    retriever = Retriever(db=MagicMock())
    # 20 条 RRF 候选(排名 1..20)
    candidates = [_make(f"c{i}", rrf_rank=i + 1) for i in range(20)]

    # 放大 rerank_candidate_k 上限, 让 cap 不生效, 单独验证 top_k 不再参与限制
    with patch.object(settings, "rerank_override", "on"), patch.object(
        settings, "rerank_candidate_k", 30
    ):
        should, k, reason = retriever._decide_rerank(
            query_text="具体的检索问题",
            top_k=5,
            candidates=candidates,
            requested_use_rerank=True,
        )

    assert should is True
    # 关键: actual_candidate_k 必须等于 RRF 候选全集(20), 不得被 final top_k=5 截断
    assert k == 20
    # 送入 rerank 的候选数 = min(k, len(candidates)) = 20, 即全部 RRF 候选
    assert min(k, len(candidates)) == 20


# 9. 完整链路: RRF 前20条 → 全部 Rerank → threshold → 最终 Top5 ------------------------
def test_full_chain_rrf20_rerank_then_threshold_then_top5():
    retriever = Retriever(db=MagicMock())
    # 20 条 RRF 候选(排名 1..20)
    candidates = [_make(f"c{i}", rrf_rank=i + 1) for i in range(20)]

    # 模拟 _decide_rerank: 给出 actual_candidate_k=20(不被 top_k=5 限制)
    with patch.object(settings, "rerank_override", "on"), patch.object(
        settings, "rerank_candidate_k", 30
    ):
        should, k, _ = retriever._decide_rerank(
            query_text="具体的检索问题",
            top_k=5,
            candidates=candidates,
            requested_use_rerank=True,
        )
    assert should and k == 20

    # 模拟 Reranker 对全部 20 条输出归一化 score: 前 12 条 >=0.5, 后 8 条 <0.5
    high = [0.99, 0.95, 0.90, 0.88, 0.85, 0.82, 0.78, 0.75, 0.70, 0.65, 0.60, 0.55]
    low = [0.45, 0.40, 0.35, 0.30, 0.25, 0.20, 0.15, 0.10]
    scores = high + low  # 长度 20
    pairs = [(i, scores[i]) for i in range(20)]

    # 全部 20 条进入 rerank(actual_candidate_k=20, 不被 top_k=5 截断)
    reranked_pairs = pairs[:k]
    assert len(reranked_pairs) == 20

    # rerank 之后先做 threshold(apply_rerank_scores 不再截断 top_k, 返回全部通过阈值的结果)
    reranked = apply_rerank_scores(candidates, reranked_pairs, threshold=0.5)
    assert len(reranked) == 12  # 全部通过 threshold, 尚未 top_k 截取

    # 再经统一后处理(去重 → 同文档限制 → final top_k → 重编号) 取 Top5
    results, pp_stats = _post_process_results(
        reranked, dedup=False, max_per_doc=0, top_k=5
    )

    # 最终取 Top5: >=0.5 中分数最高的 5 条(0.99/0.95/0.90/0.88/0.85)
    assert len(results) == 5
    assert [round(c.rerank_score, 2) for c in results] == [0.99, 0.95, 0.90, 0.88, 0.85]
    assert all(c.score_type == "rerank" for c in results)
    assert [c.final_rank for c in results] == [1, 2, 3, 4, 5]

    # threshold_passed_count 语义(与 retriever.similarity_search 中计数口径一致):
    # 通过 threshold 的候选数 = top_k 截取之前的 12, 而非最终返回的 5
    threshold_passed = len([
        c for c in candidates
        if c.rerank_score is not None and c.rerank_score >= 0.5
    ])
    assert threshold_passed == 12
    # 最终返回 5 < threshold_passed 12, 证明先 threshold 再 top_k 截取
    assert len(results) < threshold_passed


# 9b. 非法 rerank_score 必须被跳过(continue), 不静默写 0, 也不污染计数 ---------------
async def test_invalid_rerank_score_continues_and_skipped_in_run_rerank():
    retriever = Retriever(db=MagicMock())
    candidates = [_make(f"c{i}", rrf_rank=i + 1) for i in range(3)]
    # 模拟 Reranker 输出: 第 0 条非法(nan), 第 1 条正常, 第 2 条非法(inf)
    fake_output = [
        {"index": 0, "rerank_score": float("nan")},
        {"index": 1, "rerank_score": 0.8},
        {"index": 2, "rerank_score": float("inf")},
    ]
    with patch("core.rag.ranker.Reranker") as fake_reranker:
        fake_instance = fake_reranker.return_value
        fake_instance.rerank.return_value = fake_output
        pairs = await retriever._run_rerank(
            kb_id="00000000-0000-0000-0000-000000000000",
            query_text="q",
            candidates=candidates,
            actual_candidate_k=3,
            timings={},
        )
    # 非法 score 被 continue 跳过, 仅返回 1 个合法 pair
    assert pairs == [(1, 0.8)]
    # 调用方 apply_rerank_scores 不会写回非法 score
    results = apply_rerank_scores(candidates, pairs or [], threshold=0.0)
    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert results[0].rerank_score == 0.8
    # 调用方 apply_rerank_scores 不会写回非法 score
    results = apply_rerank_scores(candidates, pairs or [], threshold=0.0)
    assert len(results) == 1
    assert results[0].chunk_id == "c1"
    assert results[0].rerank_score == 0.8

