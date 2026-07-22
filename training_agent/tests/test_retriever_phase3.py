"""第三阶段双路独立召回集成测试(不触网, mock DB):

1. BM25 召回向量 TopK 之外的 chunk, 并经补充查询进入最终 TopK(matched_channels=bm25)。
2. 同 chunk 命中两路 -> 只保留一条, matched_channels=[vector,bm25]。
3. RRF 仅用排名(与原始 score 无关)。
4. 向量失败 -> 降级 bm25_only; BM25 失败 -> 降级 vector_only; 两路都失败 -> both_failed 空。
5. BM25 独有 chunk 的 matched_terms 被填充。
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import settings
from core.rag.retriever import Retriever


@pytest.fixture(autouse=True)
def _disable_context_expansion():
    """Phase 4 上下文扩展隔离: 这些 Phase 2/3 测试期间关闭扩展, expand_results 早返回不查 DB。"""
    with patch.object(settings, "context_expansion_enabled", False):
        yield

KB = "00000000-0000-0000-0000-000000000000"


def _vrow(cid, content, doc_id, title, distance):
    return {
        "id": cid, "content": content, "summary": content, "document_id": doc_id,
        "meta": {}, "title": title, "distance": distance, "vector": None,
        "hypothetical_questions": None,
    }


def _bm25_row(cid, score, terms):
    return {"chunk_id": cid, "bm25_score": score, "matched_terms": terms, "n": 100}


def _make_execute(vector_rows, bm25_rows, extra_map, vector_error=False, bm25_error=False):
    def _dispatch(sql, params=None):
        text = getattr(sql, "text", str(sql))
        if "chunk_lexical" in text:
            if bm25_error:
                raise RuntimeError("bm25 down")
            res = MagicMock()
            res.mappings().all.return_value = bm25_rows
            return res
        if "c.id = ANY" in text:
            ids = (params or {}).get("ids") or []
            res = MagicMock()
            res.mappings().all.return_value = [extra_map[c] for c in ids if c in extra_map]
            return res
        if vector_error:
            raise RuntimeError("vector down")
        res = MagicMock()
        res.mappings().all.return_value = vector_rows
        return res
    return _dispatch


def _patch_cfg():
    return patch.multiple(
        settings,
        vector_recall_top_k=2,
        bm25_recall_top_k=2,
        rrf_candidate_top_k=4,
        max_results_per_doc=10,
        rerank_override="off",
        rerank_candidate_k=20,
        bm25_max_query_terms=32,
        rrf_k=60,
        bm25_k1=1.5,
        bm25_b=0.75,
    )


# 1. BM25 召回向量 TopK 之外的 chunk -------------------------------------------------
async def test_bm25_recalls_chunks_outside_vector_topk():
    vector_rows = [
        _vrow("c1", "向量内容A", "d1", "D1", 0.1),
        _vrow("c2", "向量内容B", "d1", "D1", 0.2),
    ]
    bm25_rows = [
        _bm25_row("c3", 2.0, ["保护"]),
        _bm25_row("c4", 1.5, ["故障"]),
    ]
    extra_map = {
        "c3": _vrow("c3", "BM25独有内容C", "d2", "D2", 0.9),
        "c4": _vrow("c4", "BM25独有内容D", "d2", "D2", 0.95),
    }
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(side_effect=_make_execute(vector_rows, bm25_rows, extra_map))

    with _patch_cfg():
        results, timings = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="保护 故障", use_rerank=False, return_timings=True,
        )

    ids = {c.chunk_id for c in results}
    assert {"c3", "c4"}.issubset(ids)          # BM25 召回的 chunk 进入了最终集合
    c3 = next(c for c in results if c.chunk_id == "c3")
    assert c3.matched_channels == ["bm25"]      # BM25 独有 -> 仅 bm25 通道
    c1 = next(c for c in results if c.chunk_id == "c1")
    assert c1.matched_channels == ["vector"]
    assert timings["vector_status"] == "ok"
    assert timings["bm25_status"] == "ok"
    assert timings["degraded_mode"] == "none"


# 2. 同 chunk 命中两路 -> 只保留一条 ------------------------------------------------
async def test_same_chunk_in_both_channels_appears_once():
    vector_rows = [
        _vrow("c1", "共有内容A", "d1", "D1", 0.1),
        _vrow("c2", "向量内容B", "d1", "D1", 0.2),
    ]
    bm25_rows = [
        _bm25_row("c1", 3.0, ["保护", "故障"]),
        _bm25_row("c3", 1.0, ["配置"]),
    ]
    extra_map = {"c3": _vrow("c3", "BM25独有C", "d2", "D2", 0.9)}
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(side_effect=_make_execute(vector_rows, bm25_rows, extra_map))

    with _patch_cfg():
        results, timings = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="保护 故障 配置", use_rerank=False, return_timings=True,
        )

    ids = [c.chunk_id for c in results]
    assert ids.count("c1") == 1                  # 同名 chunk 只出现一次
    c1 = next(c for c in results if c.chunk_id == "c1")
    assert c1.matched_channels == ["vector", "bm25"]
    assert {"c1", "c2", "c3"} == set(ids)


# 3. RRF 仅用排名(与原始 score 无关) -----------------------------------------------
async def test_rrf_uses_rank_not_score():
    # 向量: c1 高 sim rank1, c2 低 sim rank2
    vector_rows = [
        _vrow("c1", "A", "d1", "D1", 0.05),
        _vrow("c2", "B", "d1", "D1", 0.9),
    ]
    # BM25: c2 高 score rank1, c1 低 score rank2 -> 排名反转
    bm25_rows = [
        _bm25_row("c2", 9.9, ["x"]),
        _bm25_row("c1", 0.1, ["y"]),
    ]
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(side_effect=_make_execute(vector_rows, bm25_rows, {}))

    with _patch_cfg():
        results, _ = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="x y", use_rerank=False, return_timings=True,
        )

    c1 = next(c for c in results if c.chunk_id == "c1")
    c2 = next(c for c in results if c.chunk_id == "c2")
    # 两者各一路 rank1 + 一路 rank2 -> RRF 分相同, 与原始 sim/BM25 绝对值无关
    assert abs(c1.rrf_score - c2.rrf_score) < 1e-9


# 4. 降级: 向量失败 -> bm25_only ----------------------------------------------------
async def test_degrade_vector_error_bm25_only():
    bm25_rows = [
        _bm25_row("c3", 2.0, ["保护"]),
        _bm25_row("c4", 1.5, ["故障"]),
    ]
    extra_map = {
        "c3": _vrow("c3", "C", "d2", "D2", 0.9),
        "c4": _vrow("c4", "D", "d2", "D2", 0.95),
    }
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(
        side_effect=_make_execute([], bm25_rows, extra_map, vector_error=True)
    )

    with _patch_cfg():
        results, timings = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="保护 故障", use_rerank=False, return_timings=True,
        )

    assert timings["vector_status"] == "error"
    assert timings["bm25_status"] == "ok"
    assert timings["degraded_mode"] == "bm25_only"
    ids = {c.chunk_id for c in results}
    assert ids == {"c3", "c4"}                 # 仅 BM25 结果
    assert all(c.matched_channels == ["bm25"] for c in results)


# 5. 降级: BM25 失败 -> vector_only -------------------------------------------------
async def test_degrade_bm25_error_vector_only():
    vector_rows = [
        _vrow("c1", "A", "d1", "D1", 0.1),
        _vrow("c2", "B", "d1", "D1", 0.2),
    ]
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(
        side_effect=_make_execute(vector_rows, [], {}, bm25_error=True)
    )

    with _patch_cfg():
        results, timings = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="保护 故障", use_rerank=False, return_timings=True,
        )

    assert timings["vector_status"] == "ok"
    assert timings["bm25_status"] == "error"
    assert timings["degraded_mode"] == "vector_only"
    assert {c.chunk_id for c in results} == {"c1", "c2"}
    assert all(c.matched_channels == ["vector"] for c in results)


# 6. 两路都失败 -> both_failed 空 --------------------------------------------------
async def test_degrade_both_error_returns_empty():
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(
        side_effect=_make_execute([], [], {}, vector_error=True, bm25_error=True)
    )

    with _patch_cfg():
        results, timings = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="保护 故障", use_rerank=False, return_timings=True,
        )

    assert results == []
    assert timings["degraded_mode"] == "both_failed"


# 7. BM25 独有 chunk 的 matched_terms 被填充 ---------------------------------------
async def test_bm25_only_chunk_matched_terms_populated():
    bm25_rows = [_bm25_row("c3", 2.0, ["保护", "差动"])]
    extra_map = {"c3": _vrow("c3", "C", "d2", "D2", 0.9)}
    retriever = Retriever(db=MagicMock())
    retriever.db.execute = AsyncMock(
        side_effect=_make_execute([], bm25_rows, extra_map, vector_error=True)
    )

    with _patch_cfg():
        results, _ = await retriever.similarity_search(
            query_vector=[0.0] * 512, kb_id=KB, top_k=10,
            threshold=0.0, query_text="保护 差动", use_rerank=False, return_timings=True,
        )

    assert len(results) == 1
    assert set(results[0].matched_terms) == {"保护", "差动"}
