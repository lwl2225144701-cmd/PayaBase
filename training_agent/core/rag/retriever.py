"""Vector Retriever - Hybrid Search with Vector + BM25 + RRF."""

import uuid
import json
import math
import asyncio
import hashlib
import logging
import re
import time
from collections import Counter
from typing import Optional
from dataclasses import dataclass

from core.infrastructure.redis.client import get_redis_client
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.tables import Chunk, Document
from core.exceptions import NotFoundException
from core.prompts import HYDE_QUERY_SYSTEM_PROMPT, HYDE_QUERY_USER_PROMPT
from core.embedding.client import EmbeddingClient

logger = logging.getLogger(__name__)

_rerank_cache = get_redis_client(db=3)


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
    min_content_length: int = 50,
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
        ids_hash = hashlib.md5(",".join(candidate_ids).encode("utf-8")).hexdigest()
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

    def _tokenize(self, text: str) -> list[str]:
        """分词"""
        return [w.lower() for w in text.split() if len(w) > 1]

    def _bm25_score(self, query: str, corpus: list[str], top_k: int = 10) -> list[tuple[int, float]]:
        """BM25算法
        
        Args:
            query: 查询
            corpus: 文档列表
            top_k: 返回数量
            
        Returns:
            [(doc_idx, score), ...]
        """
        if not corpus or not query:
            return [(i, 0.0) for i in range(len(corpus))]

        n = len(corpus)
        doc_freqs = Counter()
        for doc in corpus:
            for word in set(self._tokenize(doc)):
                doc_freqs[word] += 1

        # IDF
        idf = {}
        for word, df in doc_freqs.items():
            idf[word] = math.log((n - df + 0.5) / (df + 0.5) + 1)

        # 文档长度
        doc_lens = [len(self._tokenize(d)) for d in corpus]
        avg_len = sum(doc_lens) / n if n > 0 else 1

        query_words = self._tokenize(query)

        scores = []
        for idx, doc in enumerate(corpus):
            doc_words = self._tokenize(doc)
            word_count = Counter(doc_words)
            doc_len = doc_lens[idx]

            score = 0
            k1, b = 1.5, 0.75
            for word in query_words:
                if word in word_count:
                    tf = word_count[word]
                    numerator = tf * (k1 + 1)
                    denominator = tf + k1 * (1 - b + b * doc_len / avg_len)
                    score += idf.get(word, 0) * numerator / denominator

            scores.append((idx, score))

        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

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
        query_vector = await EmbeddingClient().embed_single(query_text)
        timings["embedding_ms"] = int((time.time() - t0) * 1000)
        if not query_vector:
            logger.warning("[RAG] query 向量化失败,返回空结果")
            return ([], timings) if return_timings else []

        if use_hyde and settings.hyde_enabled:
            try:
                t_h = time.time()
                hyde_doc = await self._generate_hyde(query_text)
                if hyde_doc:
                    hyde_vec = await EmbeddingClient().embed_single(hyde_doc)
                    if hyde_vec and len(hyde_vec) == len(query_vector):
                        alpha = float(getattr(settings, "hyde_alpha", 0.5))
                        query_vector = [
                            q * alpha + h * (1 - alpha)
                            for q, h in zip(query_vector, hyde_vec)
                        ]
                timings["hyde_ms"] = int((time.time() - t_h) * 1000)
            except Exception as e:
                logger.warning(f"[RAG] HyDE 生成失败,降级为原始 query 向量: {e}")
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

    async def _generate_hyde(self, query_text: str) -> str | None:
        """查询时 HyDE: 根据用户问题生成一篇假设性回答文档。

        仅用于检索增强,不进入最终回答;失败返回 None 由调用方降级。
        """
        from core.llm.factory import get_llm_client

        llm = get_llm_client("chat", timeout=getattr(settings, "hyde_timeout", 30.0))
        messages = [
            {"role": "system", "content": HYDE_QUERY_SYSTEM_PROMPT},
            {"role": "user", "content": HYDE_QUERY_USER_PROMPT.format(query=query_text)},
        ]
        try:
            resp = await asyncio.to_thread(llm.chat, messages)
            return (resp or "").strip() or None
        except Exception as e:
            logger.warning(f"[RAG] HyDE LLM 调用失败: {e}")
            return None

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
        """Hybrid搜索 + 元数据过滤 + Rerank
        
        Args:
            query_vector: 查询向量
            kb_id: 知识库ID
            top_k: 返回数量
            threshold: 相似度阈值
            filters: 元数据过滤条件，如 {"chunk_type": "pdf", "category": "tech"}
        """
        import time
        timings: dict[str, object] = {
            "vector_sql_ms": 0,
            "bm25_ms": 0,
            "rrf_ms": 0,
            "rerank_ms": 0,
            "retrieval_total_ms": 0,
            "rerank_decision": "off",
            "rerank_reason": "not_evaluated",
            "rerank_candidate_k": 0,
            "rerank_cache_hit": False,
            "rerank_error": "",
        }

        kb_uuid = uuid.UUID(kb_id)
        logger.info(f"[RAG] Hybrid检索 - kb={kb_id}, top_k={top_k}, filters={filters}")

        # 1. 构建SQLwith过滤条件
        vector_top_k = top_k * 3
        query_vector_str = "[" + ",".join(map(str, query_vector)) + "]"
        logger.info(f"[RAG] 向量查询准备, vector_dim={len(query_vector)}")

        where_clauses = ["d.knowledge_base_id = :kb_id", "c.vector IS NOT NULL"]
        params = {"kb_id": kb_uuid, "query_vector": query_vector_str, "limit": vector_top_k}

        # 元数据过滤
        if filters:
            for key, value in filters.items():
                where_clauses.append(f"c.meta->>:key = :{key}_value")
                params[f"{key}_value"] = value

        where_sql = " AND ".join(where_clauses)

        logger.info(f"[RAG] 执行SQL查询")
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
        t_stage = time.time()
        result = await self.db.execute(sql, params)
        rows = list(result.mappings().all())
        timings["vector_sql_ms"] = int((time.time() - t_stage) * 1000)
        logger.info(f"[RAG] 向量检索结果: {len(rows)}条")

        if not rows:
            logger.info("[RAG] 无检索结果")
            timings["retrieval_total_ms"] = (
                int(timings["vector_sql_ms"]) + int(timings["bm25_ms"]) + int(timings["rrf_ms"]) + int(timings["rerank_ms"])
            )
            return ([], timings) if return_timings else []

        # 2. 构建BM25 corpus
        corpus = []
        for row in rows:
            # 索引期不再生成 summary/HyDE，BM25 直接基于原文内容做词法匹配
            content = (row.get("summary") or row.get("content") or "")[:800]
            corpus.append(content)

        # 3. BM25搜索
        logger.info(f"[RAG] 执行BM25检索")
        t_stage = time.time()
        bm25_query = query_text or ""
        bm25_results = self._bm25_score(bm25_query, corpus, top_k=vector_top_k)
        timings["bm25_ms"] = int((time.time() - t_stage) * 1000)
        logger.info(f"[RAG] BM25结果: {len(bm25_results)}条")

        # 第二阶段: BM25 零分结果不参与 RRF 融合(也不分配 bm25_rank)。
        # 零分文档排序在末尾, 剔除后剩余结果保持原 1-based 排名不变。
        bm25_valid = _filter_valid_bm25_results(bm25_results)
        timings["bm25_valid_count"] = len(bm25_valid)
        timings["bm25_positive_count"] = len(bm25_valid)
        if len(bm25_valid) != len(bm25_results):
            logger.info(
                f"[RAG] BM25 零分剔除: {len(bm25_results) - len(bm25_valid)} 条零分结果不参与融合"
            )

        # 4. 向量分数与排名（按 distance 升序）
        logger.info(f"[RAG] 构建RRF融合")
        t_stage = time.time()

        vector_scored = []
        for i, row in enumerate(rows):
            raw = row.get("distance")
            dist = float(raw) if raw is not None else 1.0
            sim = 1.0 - dist if raw is not None else 0.0
            vector_scored.append((i, dist, sim))
        vector_scored.sort(key=lambda x: x[1])  # distance 升序
        vector_rank_map: dict[int, tuple[float, float, int]] = {}
        for rank, (i, dist, sim) in enumerate(vector_scored, 1):
            vector_rank_map[i] = (dist, sim, rank)

        # RRF 融合只接收 (doc_idx, 融合分); doc_idx 仍是 row 序号
        vector_results = [(i, sim) for (i, _dist, sim) in vector_scored]

        # 5. RRF 融合（仅用于候选排序，不代表真实相关度）
        # 标准 RRF: 仅用排名, 零分 BM25 已剔除(bm25_valid)
        combined = self._rrf_fusion(vector_results, bm25_valid, k=settings.rrf_k)
        timings["rrf_ms"] = int((time.time() - t_stage) * 1000)
        logger.info(f"[RAG] RRF融合完成, combined={len(combined)}")

        # 6. 构建候选集（按 rrf_score 排序；此处不截取 top_k）
        candidates: list[RetrievedChunk] = []
        used_ids: set = set()
        bm25_map: dict[int, tuple[float, int]] = {
            idx: (score, rank) for rank, (idx, score) in enumerate(bm25_valid, 1)
        }
        rrf_rank = 0
        for doc_idx, rrf_score in combined:
            if doc_idx < len(rows):
                row = rows[doc_idx]
                cid = row["id"]
                if cid in used_ids:
                    continue
                used_ids.add(cid)
                rrf_rank += 1
                dist, sim, vrank = vector_rank_map.get(doc_idx, (None, None, None))
                bm25_score, bm25_rank = bm25_map.get(doc_idx, (None, None))
                candidates.append(
                    RetrievedChunk(
                        chunk_id=str(cid),
                        content=row["content"],
                        document_id=str(row["document_id"]),
                        document_title=row["title"],
                        score=float(rrf_score),
                        metadata=row["meta"] or {},
                        rank=rrf_rank,
                        vector_distance=dist,
                        vector_score=sim,
                        vector_rank=vrank,
                        bm25_score=bm25_score,
                        bm25_rank=bm25_rank,
                        rrf_score=float(rrf_score),
                        rrf_rank=rrf_rank,
                    )
                )

        # 7. Rerank 精排 + threshold 过滤
        should_rerank, actual_candidate_k, rerank_reason = self._decide_rerank(
            query_text=query_text,
            top_k=top_k,
            candidates=candidates,
            requested_use_rerank=use_rerank,
        )
        timings["rerank_candidate_k"] = actual_candidate_k
        timings["rerank_reason"] = rerank_reason
        timings["rerank_decision"] = "on" if should_rerank else "off"

        trace_id = uuid.uuid4().hex
        timings["trace_id"] = trace_id
        timings["vector_result_count"] = len(rows)
        timings["bm25_result_count"] = len(bm25_results)
        timings["bm25_raw_count"] = len(bm25_results)
        timings["rrf_candidate_count"] = len(candidates)

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
            # threshold_passed_count = 通过 threshold 的候选数(在最终 top_k 截取之前),
            # 即被写回 rerank_score 且 >= threshold 的候选。注意不能用 len(results),
            # 因为 results 此时是全部通过 threshold 的 rerank 结果, 尚未经 top_k 截取/后处理。
            timings["threshold_passed_count"] = len([
                c for c in candidates
                if c.rerank_score is not None and c.rerank_score >= threshold
            ])
            logger.info(
                f"[RAG][trace={trace_id}] rerank=on 完成 | "
                f"query={query_text!r} top_k={top_k} threshold={threshold} | "
                f"vector={len(rows)} bm25={len(bm25_results)} rrf_candidates={len(candidates)} | "
                f"rerank_input={timings['rerank_input_count']} rerank_output={timings['rerank_output_count']} | "
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
            # rrf 路径不执行 threshold, 此处全部候选视为通过
            timings["threshold_passed_count"] = len(results)

        # 统一后处理: 去重 → 同文档限制 → final top_k → 重新编号。
        # 位置在 Rerank → threshold 之后、接口返回之前;
        # threshold_passed_count 已在上方统计(指 top_k 截取前通过数), 不受后处理影响。
        timings["max_results_per_doc"] = settings.max_results_per_doc
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
        if pre_pp != len(results):
            logger.info(
                f"[RAG][trace={trace_id}] 后处理: 去重移除={pp_stats['deduplicate_removed_count']} "
                f"同文档限制移除={pp_stats['document_limit_removed_count']} "
                f"top_k={top_k} ({pre_pp} -> {len(results)})"
            )

        # 每条结果记 trace（不记正文）
        for c in results:
            logger.info(
                f"[RAG][trace={trace_id}] result doc={c.document_id} chunk={c.chunk_id} | "
                f"vector_rank={c.vector_rank} bm25_rank={c.bm25_rank} | "
                f"rrf_score={c.rrf_score} rrf_rank={c.rrf_rank} | "
                f"rerank_score={c.rerank_score} final_rank={c.final_rank} score_type={c.score_type}"
            )

        timings["retrieval_total_ms"] = (
            int(timings["vector_sql_ms"]) + int(timings["bm25_ms"]) + int(timings["rrf_ms"]) + int(timings["rerank_ms"])
        )
        logger.info(f"[RAG][trace={trace_id}] Hybrid完成，返回{len(results)}条")
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
            rerank_output = await asyncio.to_thread(
                reranker.rerank,
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
        """删除文档的chunks"""
        doc_uuid = uuid.UUID(doc_id)
        query = Chunk.__table__.delete().where(Chunk.document_id == doc_uuid)
        result = await self.db.execute(query)
        await self.db.commit()
        return result.rowcount
