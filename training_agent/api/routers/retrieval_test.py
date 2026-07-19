import uuid
import time
import logging

from fastapi import APIRouter
from pydantic import BaseModel, Field

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from core.permissions import require_visible_kb
from core.exceptions import ValidationException
from core.embedding.client import EmbeddingClient
from core.rag.retriever import Retriever

logger = logging.getLogger(__name__)

router = APIRouter()


class RetrievalTestRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(5, ge=1, le=20)
    threshold: float = Field(0.2, ge=0.0, le=1.0)
    use_rerank: bool = True


@router.post("/retrieval-test", response_model=Response[dict])
async def retrieval_test(
    kb_id: str,
    body: RetrievalTestRequest,
    db: DBSession,
    current_user: CurrentUser,
):
    """
    知识库召回测试接口 (MVP)

    注意:
    1. 不改 chat_pipeline, 不影响正式聊天 RAG 链路
    2. 不改 Retriever.similarity_search 内部逻辑
    3. 不落库, 不接 LLM 生成回答
    """
    # 权限: 知识库可见性校验 (只读权限即可)
    kb = await require_visible_kb(db, current_user, uuid.UUID(kb_id))

    if not body.query.strip():
        raise ValidationException("query 不能为空")

    overall_t0 = time.time()
    timings: dict[str, object] = {
        "embedding_ms": 0,
        "retrieval_ms": 0,
        "vector_sql_ms": 0,
        "bm25_ms": 0,
        "rrf_ms": 0,
        "rerank_ms": 0,
        "retrieval_total_ms": 0,
        "rerank_decision": "off",
        "rerank_reason": "not_evaluated",
    }

    # 1. 向量化
    try:
        t0 = time.time()
        embedding = EmbeddingClient()
        query_vector = await embedding.embed_single(body.query.strip())
        timings["embedding_ms"] = int((time.time() - t0) * 1000)
    except Exception as exc:
        logger.exception(f"[RetrievalTest] Embedding failed: kb_id={kb_id}")
        raise ValidationException(f"向量化失败: {str(exc)}")

    # 2. 检索
    try:
        t0 = time.time()
        retriever = Retriever(db)
        results, retrieval_timings = await retriever.similarity_search(
            query_vector,
            str(kb.id),
            top_k=body.top_k,
            threshold=body.threshold,
            query_text=body.query.strip(),
            use_rerank=body.use_rerank,
            return_timings=True,
        )
        timings["retrieval_ms"] = int((time.time() - t0) * 1000)

        # 合并 Retriever 返回的 timings (Retriever 内部叫 retrieval_total_ms 等)
        if isinstance(retrieval_timings, dict):
            for key in (
                "vector_sql_ms",
                "bm25_ms",
                "rrf_ms",
                "rerank_ms",
                "retrieval_total_ms",
                "rerank_decision",
                "rerank_reason",
            ):
                if key in retrieval_timings:
                    timings[key] = retrieval_timings[key]
    except Exception as exc:
        logger.exception(f"[RetrievalTest] similarity_search failed: kb_id={kb_id}")
        raise ValidationException(f"检索失败: {str(exc)}")

    # 3. 构造 items
    items = []
    for idx, chunk in enumerate(results, start=1):
        items.append({
            "chunk_id": getattr(chunk, "chunk_id", None),
            "document_id": getattr(chunk, "document_id", None),
            "document_title": getattr(chunk, "document_title", ""),
            "content": getattr(chunk, "content", ""),
            # score 兼容旧字段, 恒等于 final_score
            "score": float(getattr(chunk, "score", 0.0)),
            "score_type": getattr(chunk, "score_type", "rrf"),
            "score_breakdown": {
                "vector_distance": getattr(chunk, "vector_distance", None),
                "vector_score": getattr(chunk, "vector_score", None),
                "vector_rank": getattr(chunk, "vector_rank", None),
                "bm25_score": getattr(chunk, "bm25_score", None),
                "bm25_rank": getattr(chunk, "bm25_rank", None),
                "rrf_score": getattr(chunk, "rrf_score", None),
                "rrf_rank": getattr(chunk, "rrf_rank", None),
                "rerank_score": getattr(chunk, "rerank_score", None),
                "rerank_rank": getattr(chunk, "rerank_rank", None),
            },
            "rank": getattr(chunk, "final_rank", idx) or idx,
            "metadata": getattr(chunk, "metadata", {}) or {},
        })

    total_ms = int((time.time() - overall_t0) * 1000)
    timings["retrieval_ms"] = timings.get("retrieval_ms", 0)
    timings["total_ms"] = total_ms

    return Response(data={
        "query": body.query.strip(),
        "items": items,
        "trace_id": timings.get("trace_id"),
        "timings": timings,
    })
