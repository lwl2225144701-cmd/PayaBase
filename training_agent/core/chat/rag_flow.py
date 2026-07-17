"""RAG 检索流程:从 chat_pipeline.py 中提取的纯检索职责。

只负责:
  - 判断 route 是否需要检索
  - 调用 EmbeddingClient + Retriever
  - 组装 chunks_data / citations
  - 记录 retrieval timings
  - 检索失败不抛异常,记录 error 并返回空结果

不负责:
  - LLM 调用 (chat_pipeline.py)
  - KB miss / 联网搜索逻辑 (web_search_state.py)
  - SSE 输出
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Any

from core.rag.retriever import Retriever

logger = logging.getLogger(__name__)

# 需要触发 RAG 检索的 route 集合
_RETRIEVAL_ROUTES = {
    "rag_qa",
    "content_generation",
    "ppt_generation",
    "pdf_generation",
    "document_summary",
}


@dataclass
class RagRetrievalRequest:
    """RAG 检索输入参数包。"""
    query: str
    active_kb_id: Any
    route: str


@dataclass
class RagRetrievalResult:
    """RAG 检索输出结果包。"""
    chunks_data: list[dict] = field(default_factory=list)
    citations: list[dict] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    error: str | None = None


async def retrieve_chat_context(
    *,
    db,
    request: RagRetrievalRequest,
) -> RagRetrievalResult:
    """执行 RAG 检索，返回上下文数据、引用和时间统计。

    保持与拆分前 chat_pipeline.py 中完全相同的检索逻辑:
      - embedding 使用 EmbeddingClient.embed_single()
      - retrieval 使用 Retriever.similarity_search()
      - top_k=5, threshold=0.2, use_rerank=True, return_timings=True
      - 检索失败返回空 result，写入 error，不抛异常
    """
    result = RagRetrievalResult()
    timings: dict[str, Any] = {}
    result.timings = timings

    # 判断当前 route 是否需要检索
    if not request.active_kb_id or request.route not in _RETRIEVAL_ROUTES:
        return result

    try:
        t0 = time.time()
        logger.info(f"[Timing] 开始检索, query={request.query[:30]}...")
        retriever = Retriever(db)
        retrieved, retrieval_timings = await retriever.search(
            request.query, str(request.active_kb_id),
            top_k=5, threshold=0.2,
            use_rerank=True,
            return_timings=True,
        )
        timings["retrieval_ms"] = int((time.time() - t0) * 1000)
        timings["embedding_ms"] = retrieval_timings.get("embedding_ms", 0)
        timings["hyde_ms"] = retrieval_timings.get("hyde_ms", 0)
        timings["retrieval_vector_sql_ms"] = retrieval_timings.get("vector_sql_ms", 0)
        timings["retrieval_bm25_ms"] = retrieval_timings.get("bm25_ms", 0)
        timings["retrieval_rrf_ms"] = retrieval_timings.get("rrf_ms", 0)
        timings["retrieval_rerank_ms"] = retrieval_timings.get("rerank_ms", 0)
        timings["retrieval_total_ms"] = retrieval_timings.get("retrieval_total_ms", 0)
        timings["retrieval_rerank_decision"] = retrieval_timings.get("rerank_decision", "off")
        timings["retrieval_rerank_reason"] = retrieval_timings.get("rerank_reason", "")
        timings["retrieval_rerank_candidate_k"] = retrieval_timings.get("rerank_candidate_k", 0)
        timings["retrieval_rerank_cache_hit"] = retrieval_timings.get("rerank_cache_hit", False)
        timings["retrieval_rerank_error"] = retrieval_timings.get("rerank_error", "")
        logger.info(
            f"[Timing] 混合检索完成: {timings['retrieval_ms']}ms, 返回{len(retrieved)}条, "
            f"detail={retrieval_timings}"
        )

        for c in retrieved:
            result.citations.append({
                "chunk_id": c.chunk_id,
                "document_id": c.document_id,
                "document_title": c.document_title,
                "score": c.score,
                "rank": c.rank,
            })
            result.chunks_data.append({
                "content": c.content,
                "source": c.metadata.get("source") or f"知识库-{c.document_title}",
                "chunk_type": c.metadata.get("chunk_strategy", "paragraph"),
            })
    except Exception as e:
        logger.warning(f"[Timing] RAG检索失败: {e}")
        result.error = str(e)

    return result
