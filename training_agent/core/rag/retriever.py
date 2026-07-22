"""Vector Retriever - Hybrid Search with Vector + BM25 + RRF."""

import uuid
import json
import math
import asyncio
import hashlib
import logging
import re
import time
from typing import Optional
from dataclasses import dataclass, field

import httpx

from core.infrastructure.redis.client import get_redis_client
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.tables import Chunk, Document
from core.exceptions import NotFoundException
from core.prompts import HYDE_QUERY_SYSTEM_PROMPT, HYDE_QUERY_USER_PROMPT
from core.embedding.client import EmbeddingClient
from core.rag.context_expansion import expand_results

logger = logging.getLogger(__name__)

_rerank_cache = get_redis_client(db=3)

# metadata 过滤白名单: c.meta->>'<key>' 只允许这些 key 进入 SQL, 杜绝动态 SQL 注入。
# 不在白名单内的 filter key 直接忽略(不拼进 SQL)。
FILTER_META_KEYS = {
    "model", "model_no", "device_model", "version", "versions",
    "keyword", "keywords", "standard", "protocol", "protocol_no",
}
# 仅检索已索引(ready)文档的 chunk: 向量召回用 `c.vector IS NOT NULL` 已是隐式信号,
# BM25 无 vector 列, 故显式要求文档状态为 ready, 两路过滤保持一致。
INDEXED_DOC_STATUS = "ready"


def _compile_filters(filters: Optional[dict]) -> tuple[list[tuple[str, object]], Optional[str]]:
    """把用户 filters 编译为安全结构, 杜绝动态 SQL 注入。

    Returns:
        meta_items: [(whitelisted_key, value), ...] 仅白名单内的 meta key 进入。
        doc_id:     UUID 字符串(来自 filters['document_id'])或 None。
    未列入白名单的 key 直接忽略(不拼进 SQL), 因此无法注入任意列/操作符。
    """
    meta_items: list[tuple[str, object]] = []
    doc_id: Optional[str] = None
    if not filters:
        return meta_items, doc_id
    for raw_key, value in filters.items():
        if raw_key == "document_id":
            doc_id = str(value)
            continue
        if raw_key in FILTER_META_KEYS:
            meta_items.append((raw_key, value))
        # 其余 key 忽略(防注入)
    return meta_items, doc_id


@dataclass
class RetrievedChunk:
    """检索结果块, 携带完整分数字段。

    分数语义约定:
    - rrf_score / rrf_rank: 仅多路召回的融合排序结果, **不代表真实相关度**,
      绝不可用于 percentage 展示或 threshold 过滤。
    - rerank_score / rerank_rank: Reranker 归一化后的真实相关度(0~1)。
    - final_score / final_rank: 最终对外分数。rerank 开启时 = rerank_score,
      rerank 关闭时 = rrf_score。
    - score: 为兼容旧调用方, 恒等于 final_score。
    - score_type: "rerank" 或 "rrf", 前端据此决定如何展示。
    """
    chunk_id: str
    content: str
    document_id: str
    document_title: str
    score: float
    metadata: dict
    rank: int = 0
    # 分数拆解
    vector_distance: Optional[float] = None
    vector_score: Optional[float] = None
    vector_rank: Optional[int] = None
    bm25_score: Optional[float] = None
    bm25_rank: Optional[int] = None
    rrf_score: Optional[float] = None
    rrf_rank: Optional[int] = None
    rerank_score: Optional[float] = None
    rerank_rank: Optional[int] = None
    final_score: Optional[float] = None
    final_rank: Optional[int] = None
    score_type: str = "rrf"
    matched_channels: list = field(default_factory=list)  # 命中通道: vector / bm25
    matched_terms: list = field(default_factory=list)     # BM25 命中查询词
    # ===== Phase 4 上下文扩展(检索后补充, 不改 final_score/final_rank) =====
    context_content: Optional[str] = None           # 交给 LLM 的扩展上下文
    context_group_id: Optional[str] = None          # 去重后的上下文组 ID
    parent_context_id: Optional[str] = None         # 归属的父上下文块 ID(无则 None)
    context_chunk_ids: list = field(default_factory=list)   # 本结果覆盖的全部子块 ID
    adjacent_before_ids: list = field(default_factory=list) # 命中前相邻子块 ID
    adjacent_after_ids: list = field(default_factory=list)  # 命中后相邻子块 ID
    context_source: Optional[str] = None            # child/parent/parent_adjacent/child_adjacent
    context_char_count: Optional[int] = None
    context_truncated: Optional[bool] = None
    sequence_no: Optional[int] = None  # 子块在文档中的稳定顺序(供上下文合并)


def apply_rerank_scores(
    candidates: list[RetrievedChunk],
    rerank_pairs: list[tuple[int, Optional[float]]],
    threshold: float,
) -> list[RetrievedChunk]:
    """Rerank 路径: 把 rerank 分数写回 chunk, 按 rerank_score 做 threshold 过滤。

    rerank_pairs: [(输入序号, rerank_score), ...], 已按重排后顺序排列。
    通过输入序号映射回候选块(禁止 content 匹配)。

    - score 为 None / 非数字 / NaN / Inf 时记录警告并跳过该结果, 不允许静默写成 0。
    - threshold 在 rerank 之后执行; 不足 top_k 按实际数量返回;
      全部低于 threshold 时返回空列表, 不补回低分结果。
    - 本函数**不再做最终 top_k 截断**: 由 similarity_search 的统一后处理
      (_post_process_results, 顺序: 去重 → 同文档限制 → final top_k → 重编号)
      在返回前完成。此处仅返回全部通过 threshold 的 rerank 结果。
    """
    reranked: list[RetrievedChunk] = []
    for rank, (idx, score) in enumerate(rerank_pairs, 1):
        if idx < 0 or idx >= len(candidates):
            continue
        if score is None or not isinstance(score, (int, float)) or math.isnan(score) or math.isinf(score):
            logger.warning(
                f"[RAG] apply_rerank_scores 跳过非法 score: idx={idx}, score={score}"
            )
            continue
        chunk = candidates[idx]
        chunk.rerank_score = float(score)
        chunk.rerank_rank = rank
        chunk.final_score = float(score)
        chunk.final_rank = rank
        chunk.score = float(score)
        chunk.score_type = "rerank"
        reranked.append(chunk)

    valid = [c for c in reranked if c.rerank_score is not None]
    filtered = [c for c in valid if c.rerank_score >= threshold]
    for pos, c in enumerate(filtered, 1):
        c.rank = pos
        c.final_rank = pos
    return filtered


def finalize_rrf(candidates: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """RRF 路径(rerank 未开启/未生效): final_score = rrf_score, score_type='rrf'。

    RRF 分数不是相关度, **不执行** threshold 过滤。
    本函数**不做最终 top_k 截断**: 由统一后处理 _post_process_results 完成。
    """
    for c in candidates:
        c.final_score = c.rrf_score
        c.final_rank = c.rrf_rank
        c.score = c.rrf_score if c.rrf_score is not None else 0.0
        c.score_type = "rrf"
    for pos, c in enumerate(candidates, 1):
        c.rank = pos
        c.final_rank = pos
    return candidates


def _content_dedup_key(content: str) -> str:
    """归一化正文, 用于重复切片去重(忽略大小写/首尾空白/连续空白)。"""
    if not content:
        return ""
    return re.sub(r"\s+", " ", (content or "").strip().lower())


def _filter_valid_bm25_results(bm25_results: list[tuple]) -> list[tuple]:
    """剔除 BM25 零分结果(零分不参与 RRF 融合, 也不分配 bm25_rank)。

    零分文档在 BM25 降序排列中位于末尾, 剔除后剩余结果保持原 1-based 排名不变。
    """
    return [(idx, score) for idx, score in bm25_results if score > 0]


def _post_process_results(
    results: list[RetrievedChunk],
    dedup: bool = True,
    max_per_doc: int = 0,
    top_k: int = 0,
    min_content_length: int = settings.dedup_min_content_length,
) -> tuple[list[RetrievedChunk], dict[str, object]]:
    """最终结果返回前的统一后处理。

    统一处理顺序(与用户要求一致):
      1) 内容去重: 同正文(归一化后)只保留首条; 短文本(正文长度 < min_content_length)
         只按 chunk_id 去重, 避免短噪声误并。
      2) 同文档结果数量限制: 每个有效 document_id 最多保留 max_per_doc 条;
         *候选仅含一个有效 document_id 时自动跳过限制*;
         *document_id 为空时使用 unknown:{chunk_id}*, 避免所有空 ID 被视为同一文档。
      3) final top_k 截取。
      4) 最终 rank/final_rank 重新连续编号。

    在 Rerank → threshold 之后、接口返回之前执行, 不影响
    RRF/rerank/threshold 的统计口径(threshold_passed_count 仍指 top_k 截取前通过数)。

    Returns:
        (处理后列表, 统计字典)
        统计字典含: deduplicate_before/after/removed_count,
        document_limit_enabled/before/after/removed_count。
    """
    stats: dict[str, object] = {
        "deduplicate_before_count": 0,
        "deduplicate_after_count": 0,
        "deduplicate_removed_count": 0,
        "document_limit_enabled": False,
        "document_limit_before_count": 0,
        "document_limit_after_count": 0,
        "document_limit_removed_count": 0,
    }

    # 1) 内容去重
    stats["deduplicate_before_count"] = len(results)
    out: list[RetrievedChunk] = []
    if dedup:
        seen_content: set[str] = set()
        seen_chunk: set[str] = set()
        for c in results:
            cid = c.chunk_id
            content = (c.content or "").strip()
            # 短文本: 只按 chunk_id 去重, 不参与正文归一化匹配
            if len(content) < min_content_length:
                if cid in seen_chunk:
                    stats["deduplicate_removed_count"] += 1
                    continue
                seen_chunk.add(cid)
                out.append(c)
                continue
            key = _content_dedup_key(content)
            if key and key in seen_content:
                stats["deduplicate_removed_count"] += 1
                continue
            if key:
                seen_content.add(key)
            if cid in seen_chunk:
                stats["deduplicate_removed_count"] += 1
                continue
            seen_chunk.add(cid)
            out.append(c)
    else:
        out = list(results)
    stats["deduplicate_after_count"] = len(out)

    # 2) 同文档结果数量限制
    # document_id 为空时使用 unknown:{chunk_id}, 避免所有空 ID 视为同一文档
    valid_doc_ids = {
        (c.document_id if c.document_id else f"unknown:{c.chunk_id}")
        for c in out
    }
    # 候选仅含一个有效 document_id 时自动跳过限制
    if max_per_doc and max_per_doc > 0 and len(valid_doc_ids) > 1:
        stats["document_limit_enabled"] = True
        stats["document_limit_before_count"] = len(out)
        counts: dict[str, int] = {}
        limited: list[RetrievedChunk] = []
        for c in out:
            doc_key = c.document_id if c.document_id else f"unknown:{c.chunk_id}"
            n = counts.get(doc_key, 0)
            if n >= max_per_doc:
                stats["document_limit_removed_count"] += 1
                continue
            counts[doc_key] = n + 1
            limited.append(c)
        out = limited
        stats["document_limit_after_count"] = len(out)
    else:
        stats["document_limit_before_count"] = len(out)
        stats["document_limit_after_count"] = len(out)

    # 3) final top_k 截取
    if top_k and top_k > 0:
        out = out[:top_k]

    # 4) 最终 rank/final_rank 重新连续编号
    for pos, c in enumerate(out, 1):
        c.rank = pos
        c.final_rank = pos

    return out, stats


class Retriever:
    """Vector + BM25 hybrid search with RRF."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _normalize_query(text: str) -> str:
        normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
        return normalized

    def _is_ambiguous_query(self, query: str) -> bool:
        normalized = self._normalize_query(query)
        if len(normalized) <= settings.rerank_query_len_threshold:
            return True
        fuzzy_tokens = ("介绍", "说说", "解释", "看看", "聊聊", "讲讲", "概述")
        return any(token in normalized for token in fuzzy_tokens)

    def _build_rerank_cache_key(
        self,
        kb_id: str,
        normalized_query: str,
        candidate_ids: list[str],
        candidate_k: int,
    ) -> str:
        ids_hash = hashlib.sha256(",".join(candidate_ids).encode("utf-8")).hexdigest()
        return (
            "rerank:"
            f"{kb_id}:"
            f"{normalized_query}:"
            f"{ids_hash}:"
            f"{candidate_k}:"
            f"{settings.rerank_model}:"
            f"{settings.rerank_policy_version}"
        )

    def _decide_rerank(
        self,
        query_text: str,
        top_k: int,
        candidates: list["RetrievedChunk"],
        requested_use_rerank: bool,
    ) -> tuple[bool, int, str]:
        candidate_count = len(candidates)
        if candidate_count <= 1:
            return False, 0, "insufficient_candidates"

        # actual_candidate_k 取 RRF 候选全集(受 rerank_candidate_k 上限约束),
        # **不得受最终 top_k 限制**: rerank 必须对全部 RRF 候选精排,
        # 之后再由 threshold + 最终 top_k 截取结果。
        actual_candidate_k = min(settings.rerank_candidate_k, candidate_count)
        if actual_candidate_k <= 1:
            return False, actual_candidate_k, "insufficient_candidates"

        override = (settings.rerank_override or "auto").strip().lower()
        if override not in {"auto", "on", "off"}:
            override = "auto"

        if override == "off" or not requested_use_rerank:
            return False, actual_candidate_k, "override_off"
        if override == "on":
            return True, actual_candidate_k, "override_on"

        if self._is_ambiguous_query(query_text):
            return True, actual_candidate_k, "ambiguous_query"

        top1 = candidates[0].score if candidate_count > 0 else 0.0
        top2 = candidates[1].score if candidate_count > 1 else 0.0
        score_gap = abs(top1 - top2)
        if score_gap <= settings.rerank_gap_threshold:
            return True, actual_candidate_k, "close_scores"

        return False, actual_candidate_k, "high_confidence_skip"

    def _rrf_fusion(
        self,
        vector_results: list[tuple],
        bm25_results: list[tuple],
        k: int = 60
    ) -> list[tuple]:
        """标准 Reciprocal Rank Fusion (RRF)。

        RRF = sum(1 / (k + rank)), **仅使用排名(rank), 不使用原始 score**。
        调用方负责在传入前剔除零分 BM25 结果(见 similarity_search)。

        注意: 标准 RRF 中每个召回通道只贡献其排名的倒数, 与通道自身的
        相关性分数无关 —— 这也是它与加权融合的本质区别。
        """
        rrf_scores: dict[int, float] = {}

        for rank, (doc_idx, _score) in enumerate(vector_results, 1):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0) + 1.0 / (k + rank)

        for rank, (doc_idx, _score) in enumerate(bm25_results, 1):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0) + 1.0 / (k + rank)

        return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)

    async def _bm25_search_sql(
        self,
        kb_uuid: uuid.UUID,
        terms: list[str],
        top_k: int,
        doc_uuid: Optional[uuid.UUID] = None,
        meta_items: Optional[list[tuple[str, object]]] = None,
        doc_status: str = INDEXED_DOC_STATUS,
    ) -> list[dict]:
        """标准 BM25 全库 SQL 召回(独立通道, 不读取向量 corpus)。

        公式:
            idf = ln(1 + (N - df + 0.5) / (df + 0.5))
            score = Σ idf * tf*(k1+1) / (tf + k1*(1 - b + b*dl/avgdl))
        N / avgdl / df 均限定在当前 knowledge_base_id(集合级, 不受 doc_id/meta 过滤
        影响, 保证 IDF 口径正确)。
        仅返回 score > 0; 相同分数按 chunk_id 稳定排序。
        请求阶段不加载全库 Chunk 到 Python(全在 DB 内聚合)。

        一致性过滤(与向量召回一致): document_id / 文档状态(ready) / metadata 白名单。
        这些 key 来自白名单常量或固定值, 非用户原始输入, 杜绝动态 SQL 注入。
        """
        if not terms:
            return []

        k1 = float(settings.bm25_k1)
        b = float(settings.bm25_b)

        # 一致性过滤片段(白名单 key + 固定值, 安全, 非用户原始输入)
        bm25_extra_params: dict = {"doc_status": doc_status}
        extra_joins = [
            "JOIN documents doc ON doc.id = d.document_id AND doc.status = :doc_status"
        ]
        extra_wheres: list[str] = []
        if doc_uuid is not None:
            extra_wheres.append("d.document_id = CAST(:doc_id AS uuid)")
            bm25_extra_params["doc_id"] = doc_uuid
        if meta_items:
            extra_joins.append("JOIN chunks c ON c.id = d.chunk_id")
            for i, (key, value) in enumerate(meta_items):
                extra_wheres.append(f"c.meta->>'{key}' = :meta_{i}_value")
                bm25_extra_params[f"meta_{i}_value"] = value
        extra_join_sql = "\n                 ".join(extra_joins)
        extra_where_sql = (
            "\n                  AND " + "\n                  AND ".join(extra_wheres)
            if extra_wheres
            else ""
        )

        sql = text(f"""
            WITH kb_stats AS (
                SELECT
                    COUNT(*) AS n,
                    COALESCE(AVG(NULLIF(token_count, 0)), 0) AS avgdl
                FROM chunk_lexical_documents
                WHERE knowledge_base_id = :kb_id
            ),
            df AS (
                SELECT term, COUNT(DISTINCT chunk_id) AS df
                FROM chunk_lexical_terms
                WHERE knowledge_base_id = :kb_id AND term = ANY(:terms)
                GROUP BY term
            ),
            matched AS (
                SELECT
                    t.chunk_id,
                    t.term,
                    t.term_frequency AS tf,
                    d.token_count AS dl
                FROM chunk_lexical_terms t
                JOIN chunk_lexical_documents d
                  ON d.chunk_id = t.chunk_id
                 AND d.knowledge_base_id = t.knowledge_base_id
                 {extra_join_sql}
                WHERE t.knowledge_base_id = :kb_id
                  AND t.term = ANY(:terms)
                  {extra_where_sql}
            ),
            scored AS (
                SELECT
                    m.chunk_id,
                    m.term,
                    m.tf,
                    m.dl,
                    COALESCE(df.df, 0) AS df,
                    (LN(1 + (s.n - COALESCE(df.df, 0) + 0.5) / (COALESCE(df.df, 0) + 0.5))
                       * (m.tf * (:k1 + 1))
                       / (m.tf + :k1 * (1 - :b + :b * COALESCE(m.dl / NULLIF(s.avgdl, 0), 0))))
                    AS term_score
                FROM matched m
                CROSS JOIN kb_stats s
                LEFT JOIN df ON df.term = m.term
            )
            SELECT
                chunk_id,
                SUM(term_score) AS bm25_score,
                ARRAY_AGG(DISTINCT term) AS matched_terms,
                (SELECT n FROM kb_stats) AS n
            FROM scored
            GROUP BY chunk_id
            HAVING SUM(term_score) > 0
            ORDER BY bm25_score DESC, chunk_id ASC
            LIMIT :limit
        """)
        result = await self.db.execute(
            sql,
            {
                "kb_id": kb_uuid,
                "terms": terms,
                "k1": k1,
                "b": b,
                "limit": top_k,
                **bm25_extra_params,
            },
        )
        rows = result.mappings().all()
        return [
            {
                "chunk_id": str(r["chunk_id"]),
                "bm25_score": float(r["bm25_score"]),
                "matched_terms": list(r["matched_terms"]) if r["matched_terms"] else [],
                "n": int(r["n"] or 0),
            }
            for r in rows
        ]

    async def search(
        self,
        query_text: str,
        kb_id: str,
        top_k: int = 5,
        threshold: float = 0.2,
        filters: Optional[dict] = None,
        use_hyde: bool = True,
        use_rerank: bool = True,
        return_timings: bool = False,
    ) -> list[RetrievedChunk] | tuple[list[RetrievedChunk], dict[str, object]]:
        """高层检索入口: 向量化 query + (可选)查询时 HyDE + 混合检索。

        相比索引期逐 chunk 生成 HyDE,这里只在「每次查询」用一次 LLM 生成假设文档,
        与 query 向量混合后检索。索引期因此可零 LLM 调用(纯切块 + 原文 embedding)。

        Returns:
            RetrievedChunk 列表; return_timings=True 时返回 (列表, timings)。
            timings 额外包含 embedding_ms / hyde_ms。
        """
        import time

        timings: dict[str, object] = {}
        t0 = time.time()
        try:
            query_vector = await EmbeddingClient().embed_single(query_text)
        except Exception as e:
            # Embedding 服务异常: 不得在此直接抛出导致整次检索失败。
            # 置空后继续走 similarity_search, 让 BM25 独立召回(vector_status=error,
            # degraded_mode=bm25_only); 只有向量与 BM25 都失败才返回空。
            logger.warning(f"[RAG] query 向量化异常, 降级为 BM25 单路召回: {e}")
            query_vector = None
        timings["embedding_ms"] = int((time.time() - t0) * 1000)
        if not query_vector:
            # 返回空数组或直接抛异常: 不得在此直接返回空, 置空继续 similarity_search
            # (理由同上, 让 BM25 单路降级; 双路都失败才返回空)。
            logger.warning("[RAG] query 向量化失败/为空, 降级为 BM25 单路召回")
            query_vector = None

        if use_hyde and settings.hyde_enabled and query_vector:
            try:
                t_h = time.time()
                hyde_doc, hyde_status = await self._generate_hyde(query_text)
                timings["hyde_status"] = hyde_status
                if hyde_doc:
                    hyde_vec = await EmbeddingClient().embed_single(hyde_doc)
                    if hyde_vec and len(hyde_vec) == len(query_vector):
                        alpha = float(getattr(settings, "hyde_alpha", 0.5))
                        query_vector = [
                            q * alpha + h * (1 - alpha)
                            for q, h in zip(query_vector, hyde_vec)
                        ]
                elif hyde_status in ("empty", "timeout", "error"):
                    logger.info(f"[RAG] HyDE 降级({hyde_status}), 使用原始 query 向量")
                timings["hyde_ms"] = int((time.time() - t_h) * 1000)
            except Exception as e:
                logger.warning(f"[RAG] HyDE 生成失败,降级为原始 query 向量: {e}")
                timings["hyde_status"] = "error"
                timings["hyde_ms"] = 0

        result = await self.similarity_search(
            query_vector,
            kb_id,
            top_k=top_k,
            threshold=threshold,
            filters=filters,
            query_text=query_text,
            use_rerank=use_rerank,
            return_timings=return_timings,
        )
        if return_timings and isinstance(result, tuple):
            retrieved, sub = result
            sub.update(timings)
            return retrieved, sub
        return result

    async def _generate_hyde(self, query_text: str) -> tuple[str | None, str]:
        """查询时 HyDE: 根据用户问题生成一篇假设性回答文档。

        仅用于检索增强,不进入最终回答。返回 ``(文本, 状态)``:
        - ``("...", "ok")``      正常生成;
        - ``(None, "empty")``     LLM 返回空字符串;
        - ``(None, "timeout")``   LLM 调用超时(区分于其他异常, 便于线上排查);
        - ``(None, "error")``     其他异常。

        调用方据状态写 ``timings["hyde_status"]``, 失败均降级为原始 query 向量。
        """
        from core.llm.factory import get_llm_client

        llm = get_llm_client("chat", timeout=getattr(settings, "hyde_timeout", 30.0))
        messages = [
            {"role": "system", "content": HYDE_QUERY_SYSTEM_PROMPT},
            {"role": "user", "content": HYDE_QUERY_USER_PROMPT.format(query=query_text)},
        ]
        try:
            resp = await asyncio.to_thread(llm.chat, messages)
            text = (resp or "").strip()
            if not text:
                logger.warning("[RAG] HyDE LLM 返回空字符串, 降级为原始 query 向量")
                return None, "empty"
            return text, "ok"
        except (httpx.TimeoutException, TimeoutError) as e:
            logger.warning(f"[RAG] HyDE LLM 调用超时(降级): {type(e).__name__}: {e}")
            return None, "timeout"
        except Exception as e:
            logger.warning(f"[RAG] HyDE LLM 调用失败(降级): {type(e).__name__}: {e}")
            return None, "error"

    async def similarity_search(
        self,
        query_vector: list[float],
        kb_id: str,
        top_k: int = 5,
        threshold: float = 0.2,
        filters: Optional[dict] = None,
        query_text: str = "",
        use_rerank: bool = True,
        return_timings: bool = False,
    ) -> list[RetrievedChunk] | tuple[list[RetrievedChunk], dict[str, object]]:
        """双路独立召回 + 标准 RRF + Rerank + 后处理(第三阶段)。

        链路(固定):
        向量独立召回 Top{VECTOR_RECALL_TOP_K}
        → BM25 独立全库召回 Top{BM25_RECALL_TOP_K}
        → 按 chunk_id 合并(禁 content 匹配)
        → 标准 RRF Top{RRF_CANDIDATE_TOP_K}(仅用排名)
        → Rerank Top{RERANK_CANDIDATE_K}
        → threshold → 去重 → 同文档限制 → final top_k → final_rank 重编号

        降级: 单路失败则另一路继续; 两路都失败返回空 + degraded_mode=both_failed。
        """
        import time

        trace_id = uuid.uuid4().hex
        timings: dict[str, object] = {
            "trace_id": trace_id,
            "vector_sql_ms": 0,
            "bm25_sql_ms": 0,
            "bm25_ms": 0,
            "rrf_ms": 0,
            "rerank_ms": 0,
            "retrieval_total_ms": 0,
            "rerank_decision": "off",
            "rerank_reason": "not_evaluated",
            "rerank_candidate_k": 0,
            "rerank_cache_hit": False,
            "rerank_error": "",
            "vector_result_count": 0,
            "bm25_result_count": 0,
            "bm25_query_term_count": 0,
            "bm25_index_document_count": 0,
            "rrf_candidate_count_before_limit": 0,
            "rrf_candidate_count": 0,
            "rerank_input_count": 0,
            "rerank_output_count": 0,
            "threshold_passed_count": 0,
            "final_result_count": 0,
            "vector_status": "ok",
            "bm25_status": "ok",
            "degraded_mode": "none",
            "degraded_reason": "",
            "max_results_per_doc": settings.max_results_per_doc,
        }

        kb_uuid = uuid.UUID(kb_id)
        logger.info(f"[RAG] 双路检索 - kb={kb_id}, top_k={top_k}, filters={filters}")
        # filters 在向量/BM25 两路共用同一份编译结果, 保证过滤一致
        meta_items, doc_id = _compile_filters(filters)

        vector_top_k = settings.vector_recall_top_k
        bm25_top_k = settings.bm25_recall_top_k
        rrf_top_k = settings.rrf_candidate_top_k

        # ===== 1. 向量独立召回 =====
        vector_status = "ok"
        vector_rows: list[dict] = []
        vector_row_map: dict[str, dict] = {}
        vector_rank_map: dict[str, tuple] = {}
        t_stage = time.time()
        try:
            if not query_vector:
                raise ValueError("query_vector 为空")
            query_vector_str = "[" + ",".join(map(str, query_vector)) + "]"
            where_clauses = ["d.knowledge_base_id = :kb_id", "c.vector IS NOT NULL"]
            params: dict = {
                "kb_id": kb_uuid,
                "query_vector": query_vector_str,
                "limit": vector_top_k,
                "doc_status": INDEXED_DOC_STATUS,
            }
            # filters: 白名单 meta key + document_id + 文档状态, 禁止动态 SQL 注入。
            for i, (key, value) in enumerate(meta_items):
                # key 来自白名单常量, 非用户原始输入, 安全; value 以独立参数名绑定。
                where_clauses.append(f"c.meta->>'{key}' = :meta_{i}_value")
                params[f"meta_{i}_value"] = value
            if doc_id:
                where_clauses.append("c.document_id = CAST(:doc_id AS uuid)")
                params["doc_id"] = uuid.UUID(doc_id)
            # 仅检索已索引(ready)文档的 chunk, 与 BM25 通道保持一致
            where_clauses.append("d.status = :doc_status")
            where_sql = " AND ".join(where_clauses)
            sql = text(f"""
                SELECT
                    c.id, c.content, c.summary, c.document_id, c.vector, c.meta,
                    c.hypothetical_questions, d.title,
                    c.vector <=> CAST(:query_vector AS vector(512)) AS distance
                FROM chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE {where_sql}
                ORDER BY distance
                LIMIT :limit
            """)
            result = await self.db.execute(sql, params)
            for row in result.mappings().all():
                vector_rows.append(row)
            timings["vector_sql_ms"] = int((time.time() - t_stage) * 1000)
            for rank, row in enumerate(sorted(vector_rows, key=lambda r: float(r["distance"])), 1):
                cid = str(row["id"])
                dist = float(row["distance"])
                sim = 1.0 - dist
                vector_row_map[cid] = row
                vector_rank_map[cid] = (dist, sim, rank)
        except Exception as e:
            vector_status = "error"
            timings["vector_sql_ms"] = int((time.time() - t_stage) * 1000)
            logger.warning(f"[RAG][trace={trace_id}] 向量召回失败: {e}")

        # ===== 2. BM25 独立全库召回 =====
        bm25_status = "ok"
        bm25_results: list[tuple] = []  # (chunk_id, score)
        bm25_term_map: dict[str, list] = {}
        bm25_index_count = 0
        t_stage = time.time()
        try:
            from core.rag.tokenizer import tokenize_query
            terms = tokenize_query(query_text)[: settings.bm25_max_query_terms]
            timings["bm25_query_term_count"] = len(terms)
            bm25_rows = (
                await self._bm25_search_sql(
                    kb_uuid,
                    terms,
                    bm25_top_k,
                    doc_uuid=(uuid.UUID(doc_id) if doc_id else None),
                    meta_items=meta_items,
                )
                if terms
                else []
            )
            timings["bm25_sql_ms"] = int((time.time() - t_stage) * 1000)
            timings["bm25_ms"] = timings["bm25_sql_ms"]
            for r in bm25_rows:
                bm25_results.append((r["chunk_id"], r["bm25_score"]))
                bm25_term_map[r["chunk_id"]] = r["matched_terms"]
            # 防御性: 仅保留严格 >0 的 BM25 结果(零/负分不参与 RRF 融合)
            bm25_results = _filter_valid_bm25_results(bm25_results)
            bm25_index_count = bm25_rows[0]["n"] if bm25_rows else 0
            bm25_status = "empty" if not bm25_results else "ok"
        except Exception as e:
            bm25_status = "error"
            timings["bm25_sql_ms"] = int((time.time() - t_stage) * 1000)
            timings["bm25_ms"] = timings["bm25_sql_ms"]
            logger.warning(f"[RAG][trace={trace_id}] BM25 全库召回失败: {e}")

        timings["vector_status"] = vector_status
        timings["bm25_status"] = bm25_status
        timings["vector_result_count"] = len(vector_rows)
        timings["bm25_result_count"] = len(bm25_results)
        timings["bm25_index_document_count"] = bm25_index_count

        # ===== 降级判定 =====
        degraded_mode = "none"
        degraded_reason = ""
        if vector_status == "error" and bm25_status == "error":
            # 两路都**失败**(error), 非"空结果"。空结果不是失败, 走单路降级。
            timings["degraded_mode"] = "both_failed"
            timings["degraded_reason"] = "vector_error_and_bm25_error"
            timings["retrieval_total_ms"] = (
                int(timings["vector_sql_ms"]) + int(timings["bm25_ms"])
                + int(timings["rrf_ms"]) + int(timings["rerank_ms"])
            )
            logger.warning(f"[RAG][trace={trace_id}] 双路检索均失败, 返回空")
            return ([], timings) if return_timings else []
        if vector_status == "error":
            degraded_mode = "bm25_only"
            degraded_reason = "vector_recall_error"
        elif bm25_status == "error":
            degraded_mode = "vector_only"
            degraded_reason = "bm25_recall_error"
        elif not vector_rows and not bm25_results:
            timings["retrieval_total_ms"] = (
                int(timings["vector_sql_ms"]) + int(timings["bm25_ms"])
            )
            return ([], timings) if return_timings else []
        timings["degraded_mode"] = degraded_mode
        timings["degraded_reason"] = degraded_reason

        # ===== 3. 合并: 按 chunk_id(禁止 content 匹配) =====
        all_cids: list[str] = []
        seen_cids: set[str] = set()
        for cid in vector_rank_map:
            if cid not in seen_cids:
                all_cids.append(cid)
                seen_cids.add(cid)
        for cid, _ in bm25_results:
            if cid not in seen_cids:
                all_cids.append(cid)
                seen_cids.add(cid)
        cid_to_idx = {cid: i for i, cid in enumerate(all_cids)}

        # 补充查询 BM25 独有 chunk 的完整信息(仅查命中 chunk, 不加载全库)
        bm25_only_cids = [cid for cid in all_cids if cid not in vector_row_map]
        extra_row_map: dict[str, dict] = {}
        if bm25_only_cids:
            try:
                extra_sql = text("""
                    SELECT c.id, c.content, c.document_id, c.meta, d.title
                    FROM chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE c.id = ANY(CAST(:ids AS uuid[]))
                """)
                extra_res = await self.db.execute(extra_sql, {"ids": bm25_only_cids})
                for row in extra_res.mappings().all():
                    extra_row_map[str(row["id"])] = row
            except Exception as e:
                logger.warning(f"[RAG][trace={trace_id}] 补充查询 BM25 独有 chunk 失败: {e}")

        # ===== 4. 标准 RRF(仅用排名, 不使用原始 score) =====
        t_stage = time.time()
        vector_for_rrf = [
            (cid_to_idx[cid], sim)
            for cid, (_d, sim, _r) in sorted(vector_rank_map.items(), key=lambda kv: kv[1][2])
        ]
        bm25_for_rrf = [(cid_to_idx[cid], score) for cid, score in bm25_results]
        combined = self._rrf_fusion(vector_for_rrf, bm25_for_rrf, k=settings.rrf_k)
        timings["rrf_ms"] = int((time.time() - t_stage) * 1000)
        timings["rrf_candidate_count_before_limit"] = len(combined)
        combined = combined[:rrf_top_k]
        timings["rrf_candidate_count"] = len(combined)
        logger.info(
            f"[RAG][trace={trace_id}] RRF 融合完成, before_limit="
            f"{timings['rrf_candidate_count_before_limit']} after_limit={len(combined)}"
        )

        # ===== 5. 构建候选集 =====
        candidates: list[RetrievedChunk] = []
        bm25_rank_map = {
            cid: (score, rank) for rank, (cid, score) in enumerate(bm25_results, 1)
        }
        rrf_rank = 0
        for idx, rrf_score in combined:
            cid = all_cids[idx]
            row = vector_row_map.get(cid) or extra_row_map.get(cid)
            if row is None:
                continue
            vinfo = vector_rank_map.get(cid)
            binfo = bm25_rank_map.get(cid)
            channels: list[str] = []
            if vinfo:
                channels.append("vector")
            if binfo:
                channels.append("bm25")
            rrf_rank += 1
            candidates.append(
                RetrievedChunk(
                    chunk_id=cid,
                    content=row["content"],
                    document_id=str(row["document_id"]),
                    document_title=row["title"],
                    score=float(rrf_score),
                    metadata=row["meta"] or {},
                    rank=rrf_rank,
                    vector_distance=vinfo[0] if vinfo else None,
                    vector_score=vinfo[1] if vinfo else None,
                    vector_rank=vinfo[2] if vinfo else None,
                    bm25_score=binfo[0] if binfo else None,
                    bm25_rank=binfo[1] if binfo else None,
                    rrf_score=float(rrf_score),
                    rrf_rank=rrf_rank,
                    matched_channels=channels,
                    matched_terms=bm25_term_map.get(cid, []),
                )
            )

        # ===== 6. Rerank 精排 + threshold =====
        should_rerank, actual_candidate_k, rerank_reason = self._decide_rerank(
            query_text=query_text,
            top_k=top_k,
            candidates=candidates,
            requested_use_rerank=use_rerank,
        )
        timings["rerank_candidate_k"] = actual_candidate_k
        timings["rerank_reason"] = rerank_reason
        timings["rerank_decision"] = "on" if should_rerank else "off"

        reranked_pairs: list[tuple[int, Optional[float]]] | None = None
        if should_rerank:
            reranked_pairs = await self._run_rerank(
                kb_id=kb_id,
                query_text=query_text,
                candidates=candidates,
                actual_candidate_k=actual_candidate_k,
                timings=timings,
            )

        if should_rerank and reranked_pairs is not None:
            results = apply_rerank_scores(candidates, reranked_pairs, threshold)
            timings["rerank_input_count"] = min(actual_candidate_k, len(candidates))
            timings["rerank_output_count"] = len([p for p in reranked_pairs if p[1] is not None])
            timings["threshold_passed_count"] = len([
                c for c in candidates
                if c.rerank_score is not None and c.rerank_score >= threshold
            ])
            logger.info(
                f"[RAG][trace={trace_id}] rerank=on 完成 | "
                f"query={query_text!r} top_k={top_k} threshold={threshold} | "
                f"vector={len(vector_rows)} bm25={len(bm25_results)} "
                f"rrf_candidates={len(candidates)} | "
                f"rerank_input={timings['rerank_input_count']} "
                f"rerank_output={timings['rerank_output_count']} | "
                f"threshold_passed={timings['threshold_passed_count']}"
            )
        else:
            logger.info(
                f"[RAG][trace={trace_id}] rerank disabled, threshold skipped because "
                f"RRF score is not a relevance score; reason={rerank_reason}"
            )
            results = finalize_rrf(candidates)
            timings["rerank_input_count"] = 0
            timings["rerank_output_count"] = 0
            timings["threshold_passed_count"] = len(results)

        # ===== 7. 统一后处理(去重 → 同文档限制 → final top_k → 重编号) =====
        # 位置在 Rerank → threshold 之后、接口返回之前;
        # threshold_passed_count 已在上方统计(指 top_k 截取前通过数), 不受后处理影响。
        pre_pp = len(results)
        results, pp_stats = _post_process_results(
            results,
            dedup=True,
            max_per_doc=settings.max_results_per_doc,
            top_k=top_k,
            min_content_length=settings.dedup_min_content_length,
        )
        timings["deduplicate_before_count"] = pp_stats["deduplicate_before_count"]
        timings["deduplicate_after_count"] = pp_stats["deduplicate_after_count"]
        timings["deduplicate_removed_count"] = pp_stats["deduplicate_removed_count"]
        timings["document_limit_enabled"] = pp_stats["document_limit_enabled"]
        timings["document_limit_before_count"] = pp_stats["document_limit_before_count"]
        timings["document_limit_after_count"] = pp_stats["document_limit_after_count"]
        timings["document_limit_removed_count"] = pp_stats["document_limit_removed_count"]
        # final_result_count 必须在全部后处理 + top_k 完成后统计
        timings["final_result_count"] = len(results)

        # ===== 8. Phase 4 上下文扩展(final top_k 之后, 不修改 final_result_count/score/rank) =====
        # 关闭 context_expansion_enabled 时 expand_results 原样返回, 行为与第三阶段一致。
        results, ctx_stats = await expand_results(self.db, results)
        timings.update(ctx_stats)
        logger.info(
            f"[RAG][trace={trace_id}] 上下文扩展: parent_hit="
            f"{ctx_stats['parent_context_hit_count']} adjacent="
            f"{ctx_stats['adjacent_chunk_count']} groups_before="
            f"{ctx_stats['context_group_count_before_merge']} groups_after="
            f"{ctx_stats['context_group_count_after_merge']} dup_removed="
            f"{ctx_stats['context_duplicate_removed_count']} truncated="
            f"{ctx_stats['context_truncated_count']} total_chars="
            f"{ctx_stats['context_total_chars']} ms={ctx_stats['context_expand_ms']}"
        )

        if pre_pp != len(results):
            logger.info(
                f"[RAG][trace={trace_id}] 后处理: 去重移除={pp_stats['deduplicate_removed_count']} "
                f"同文档限制移除={pp_stats['document_limit_removed_count']} "
                f"top_k={top_k} ({pre_pp} -> {len(results)})"
            )

        # 每条结果记 trace(不记正文)
        for c in results:
            logger.info(
                f"[RAG][trace={trace_id}] result doc={c.document_id} chunk={c.chunk_id} | "
                f"channels={c.matched_channels} | "
                f"vector_rank={c.vector_rank} bm25_rank={c.bm25_rank} | "
                f"rrf_score={c.rrf_score} rrf_rank={c.rrf_rank} | "
                f"rerank_score={c.rerank_score} final_rank={c.final_rank} "
                f"score_type={c.score_type}"
            )

        timings["retrieval_total_ms"] = (
            int(timings["vector_sql_ms"]) + int(timings["bm25_ms"])
            + int(timings["rrf_ms"]) + int(timings["rerank_ms"])
        )
        logger.info(f"[RAG][trace={trace_id}] 双路检索完成, 返回{len(results)}条")
        return (results, timings) if return_timings else results

    async def _run_rerank(
        self,
        kb_id: str,
        query_text: str,
        candidates: list[RetrievedChunk],
        actual_candidate_k: int,
        timings: dict[str, object],
    ) -> list[tuple[int, Optional[float]]] | None:
        """调用 Reranker 精排, 返回 [(输入序号, rerank_score), ...]（按重排后顺序）。

        通过「输入序号」映射回候选块, 禁止 content 文本匹配。
        失败/空结果时返回 None, 由调用方降级为 RRF 路径。
        """
        rerank_candidates = candidates[:actual_candidate_k]
        candidate_ids = [c.chunk_id for c in rerank_candidates]
        normalized_query = self._normalize_query(query_text or "search")
        cache_key = self._build_rerank_cache_key(
            kb_id=kb_id,
            normalized_query=normalized_query,
            candidate_ids=candidate_ids,
            candidate_k=actual_candidate_k,
        )
        try:
            cached = _rerank_cache.get(cache_key)
        except Exception as e:
            cached = None
            logger.warning(f"[RAG] 读取Rerank缓存失败: {e}")

        if cached:
            try:
                cached_list = json.loads(cached)
                cached_map = {c.chunk_id: c for c in rerank_candidates}
                ordered: list[tuple[int, Optional[float]]] = []
                for entry in cached_list:
                    cid = entry.get("id")
                    c = cached_map.get(cid)
                    if c is None:
                        continue
                    idx = rerank_candidates.index(c)
                    ordered.append((idx, entry.get("score")))
                if len(ordered) == len(rerank_candidates):
                    timings["rerank_cache_hit"] = True
                    return ordered
            except Exception as e:
                logger.warning(f"[RAG] 解析Rerank缓存失败: {e}")

        try:
            from core.rag.ranker import Reranker as RerankClient

            reranker = RerankClient()
            chunk_dicts = [{"content": c.content, "score": c.score} for c in rerank_candidates]
            t_stage = time.time()
            rerank_output = await reranker.rerank_async(
                query_text or "search",
                chunk_dicts,
                actual_candidate_k,
                True,
            )
            timings["rerank_ms"] = int((time.time() - t_stage) * 1000)
            if not rerank_output:
                timings["rerank_reason"] = "rerank_failed_fallback"
                timings["rerank_error"] = "empty_rerank_result"
                logger.warning("[RAG] Rerank 返回空, 降级为 RRF 路径")
                return None

            pairs: list[tuple[int, Optional[float]]] = []
            for rc in rerank_output:
                idx = int(rc.get("index", -1))
                if idx < 0 or idx >= len(rerank_candidates):
                    continue
                score = rc.get("rerank_score")
                if score is None or not isinstance(score, (int, float)) or math.isnan(score) or math.isinf(score):
                    logger.warning(
                        f"[RAG] Rerank 结果 score 非法(chunk={rerank_candidates[idx].chunk_id}, "
                        f"score={score}), 跳过该候选(continue)"
                    )
                    continue
                pairs.append((idx, float(score)))
            if not pairs:
                timings["rerank_reason"] = "rerank_failed_fallback"
                timings["rerank_error"] = "rerank_mapping_empty"
                return None
            try:
                _rerank_cache.setex(
                    cache_key,
                    settings.rerank_cache_ttl_sec,
                    json.dumps([
                        {"id": rerank_candidates[idx].chunk_id, "score": s}
                        for idx, s in pairs
                    ]),
                )
            except Exception as e:
                logger.warning(f"[RAG] 写入Rerank缓存失败: {e}")
            return pairs
        except Exception as e:
            timings["rerank_reason"] = "rerank_failed_fallback"
            timings["rerank_error"] = str(e)[:300]
            logger.warning(f"[RAG] Rerank失败: {e}")
            return None

    async def similarity_search_by_text(
        self,
        query_text: str,
        query_embedding: list[float],
        kb_id: str,
        top_k: int = 5,
        threshold: float = 0.2,
        return_timings: bool = False,
    ) -> list[RetrievedChunk] | tuple[list[RetrievedChunk], dict[str, object]]:
        """兼容接口"""
        return await self.similarity_search(query_embedding, kb_id, top_k, threshold, query_text=query_text, return_timings=return_timings)

    async def get_chunks_by_document(
        self,
        doc_id: str,
        limit: Optional[int] = None,
    ) -> list[Chunk]:
        """获取文档的所有chunks"""
        doc_uuid = uuid.UUID(doc_id)
        query = select(Chunk).where(Chunk.document_id == doc_uuid)
        if limit:
            query = query.limit(limit)
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def count_chunks(self, kb_id: str) -> int:
        """统计chunks数量"""
        kb_uuid = uuid.UUID(kb_id)
        query = (
            select(func.count(Chunk.id))
            .join(Document, Chunk.document_id == Document.id)
            .where(Document.knowledge_base_id == kb_uuid)
        )
        result = await self.db.execute(query)
        return result.scalar() or 0

    async def delete_chunks_by_document(self, doc_id: str) -> int:
        """删除文档的chunks, 并同步清理词法索引。

        显式清理词法索引若失败必须抛出, 禁止在已 abort 的事务上继续提交(否则报
        "current transaction is aborted")。chunk_lexical_* 的 ON DELETE CASCADE
        才是真正的兜底; 这里不再吞掉异常。
        """
        doc_uuid = uuid.UUID(doc_id)
        from core.rag.lexical_index import delete_by_document_async
        # 显式清理词法索引(失败直接抛出, 由上层回滚); FK 级联为兜底
        await delete_by_document_async(self.db, doc_uuid)
        query = Chunk.__table__.delete().where(Chunk.document_id == doc_uuid)
        result = await self.db.execute(query)
        await self.db.commit()
        return result.rowcount
