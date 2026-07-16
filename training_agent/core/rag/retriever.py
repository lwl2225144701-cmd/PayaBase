"""Vector Retriever - Hybrid Search with Vector + BM25 + RRF."""

import uuid
import json
import math
import asyncio
import hashlib
import logging
import re
from collections import Counter
from typing import Optional
from dataclasses import dataclass

import redis
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from models.tables import Chunk, Document
from core.exceptions import NotFoundException
from core.prompts import HYDE_QUERY_SYSTEM_PROMPT, HYDE_QUERY_USER_PROMPT
from core.embedding.client import EmbeddingClient

logger = logging.getLogger(__name__)

_rerank_cache = redis.Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    db=3,
    decode_responses=True,
)


@dataclass
class RetrievedChunk:
    """Retrieved chunk with score."""
    chunk_id: str
    content: str
    document_id: str
    document_title: str
    score: float
    metadata: dict
    rank: int = 0


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

        actual_candidate_k = min(settings.rerank_candidate_k, candidate_count, top_k)
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
        """Reciprocal Rank Fusion
        
        RRF = sum(1 / (k + rank))
        """
        rrf_scores = {}
        
        for rank, (doc_idx, score) in enumerate(vector_results, 1):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0) + score / (k + rank)
        
        for rank, (doc_idx, score) in enumerate(bm25_results, 1):
            rrf_scores[doc_idx] = rrf_scores.get(doc_idx, 0) + score / (k + rank)
        
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

        llm = get_llm_client("chat")
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
        
        # 4. 向量结果
        logger.info(f"[RAG] 构建RRF融合")
        t_stage = time.time()
        vector_results = []
        for i, row in enumerate(rows):
            dist = row.get("distance", 1.0)
            vector_results.append((i, 1 - float(dist) if dist else 0))
        
        # 5. RRF融合
        combined = self._rrf_fusion(vector_results, bm25_results)
        timings["rrf_ms"] = int((time.time() - t_stage) * 1000)
        logger.info(f"[RAG] RRF融合完成, combined={len(combined)}")
        
        # 6. 构建返回（预排序结果，用于Rerank）
        retrieved = []
        used_ids = set()
        logger.info(f"[RAG] 构建返回结果")
        
        for rank, (doc_idx, rrf_score) in enumerate(combined, 1):
            if doc_idx < len(rows):
                row = rows[doc_idx]
                if row["id"] in used_ids:
                    continue
                used_ids.add(row["id"])
                retrieved.append(
                    RetrievedChunk(
                        chunk_id=str(row["id"]),
                        content=row["content"],
                        document_id=str(row["document_id"]),
                        document_title=row["title"],
                        score=float(rrf_score),
                        metadata=row["meta"] or {},
                        rank=rank,
                    )
                )
            if len(retrieved) >= top_k:
                break
        
        # 7. Rerank重排序（策略触发 + 候选限制 + 缓存 + 失败降级）
        should_rerank, actual_candidate_k, rerank_reason = self._decide_rerank(
            query_text=query_text,
            top_k=top_k,
            candidates=retrieved,
            requested_use_rerank=use_rerank,
        )
        timings["rerank_candidate_k"] = actual_candidate_k
        timings["rerank_reason"] = rerank_reason
        timings["rerank_decision"] = "on" if should_rerank else "off"

        if should_rerank:
            logger.info(f"[RAG] 执行Rerank重排序, candidates={actual_candidate_k}, reason={rerank_reason}")
            rerank_candidates = retrieved[:actual_candidate_k]
            untouched_candidates = retrieved[actual_candidate_k:]
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

            reranked_candidates: list[RetrievedChunk] | None = None
            if cached:
                try:
                    cached_ids = json.loads(cached)
                    cached_map = {c.chunk_id: c for c in rerank_candidates}
                    ordered = [cached_map[cid] for cid in cached_ids if cid in cached_map]
                    if len(ordered) == len(rerank_candidates):
                        reranked_candidates = ordered
                        timings["rerank_cache_hit"] = True
                except Exception as e:
                    logger.warning(f"[RAG] 解析Rerank缓存失败: {e}")

            if reranked_candidates is None:
                try:
                    from core.rag.ranker import Reranker as RerankClient

                    reranker = RerankClient()
                    chunk_dicts = [
                        {"content": c.content, "score": c.score}
                        for c in rerank_candidates
                    ]
                    t_stage = time.time()
                    reranked = await asyncio.to_thread(
                        reranker.rerank,
                        query_text or "search",
                        chunk_dicts,
                        actual_candidate_k,
                        True,
                    )
                    timings["rerank_ms"] = int((time.time() - t_stage) * 1000)
                    if not reranked:
                        timings["rerank_reason"] = "rerank_failed_fallback"
                        timings["rerank_error"] = "empty_rerank_result"
                        reranked_candidates = rerank_candidates
                    else:
                        # Map content occurrence to candidate order, fallback to original order if mismatch.
                        used = [False] * len(rerank_candidates)
                        ordered: list[RetrievedChunk] = []
                        for rc in reranked:
                            content = rc.get("content", "")
                            matched_idx = -1
                            for idx, candidate in enumerate(rerank_candidates):
                                if not used[idx] and candidate.content == content:
                                    matched_idx = idx
                                    break
                            if matched_idx >= 0:
                                used[matched_idx] = True
                                ordered.append(rerank_candidates[matched_idx])
                        if len(ordered) != len(rerank_candidates):
                            timings["rerank_reason"] = "rerank_failed_fallback"
                            timings["rerank_error"] = "rerank_mapping_mismatch"
                            reranked_candidates = rerank_candidates
                        else:
                            reranked_candidates = ordered
                            try:
                                _rerank_cache.setex(
                                    cache_key,
                                    settings.rerank_cache_ttl_sec,
                                    json.dumps([c.chunk_id for c in reranked_candidates]),
                                )
                            except Exception as e:
                                logger.warning(f"[RAG] 写入Rerank缓存失败: {e}")
                except Exception as e:
                    timings["rerank_reason"] = "rerank_failed_fallback"
                    timings["rerank_error"] = str(e)[:300]
                    logger.warning(f"[RAG] Rerank失败: {e}")
                    reranked_candidates = rerank_candidates

            retrieved = reranked_candidates + untouched_candidates
            for i, chunk in enumerate(retrieved, 1):
                chunk.rank = i
        
        # 兜底
        if not retrieved and rows:
            logger.info(f"[RAG] 触发兜底策略")
            row = rows[0]
            retrieved.append(
                RetrievedChunk(
                    chunk_id=str(row["id"]),
                    content=row["content"],
                    document_id=str(row["document_id"]),
                    document_title=row["title"],
                    score=0.5,
                    metadata=row["meta"] or {},
                    rank=1,
                )
            )
        
        timings["retrieval_total_ms"] = (
            int(timings["vector_sql_ms"]) + int(timings["bm25_ms"]) + int(timings["rrf_ms"]) + int(timings["rerank_ms"])
        )
        logger.info(f"[RAG] Hybrid完成，返回{len(retrieved)}条, timings={timings}")
        return (retrieved, timings) if return_timings else retrieved

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
