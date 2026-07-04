"""Reranker.

bge-rerank for result re-ranking.
"""

import logging
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


class Reranker:
    """bge-rerank re-ranking."""

    def __init__(self, base_url: Optional[str] = None):
        """Initialize reranker.

        Args:
            base_url: Rerank service URL
        """
        self.base_url = base_url or settings.rerank_service_url

    def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_k: int = 5,
        raise_on_failure: bool = False,
    ) -> list[dict]:
        """Re-rank chunks.

        Args:
            query: Query text
            chunks: List of chunk dicts
            top_k: Number of results

        Returns:
            Re-ranked chunks
        """
        if not chunks:
            return []

        logger.info(f"[Reranker] 请求重排序, query={query[:30]}, chunks={len(chunks)}, top_k={top_k}")
        
        texts = [chunk["content"] for chunk in chunks]

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{self.base_url}/rerank",
                    json={
                        "query": query,
                        "texts": texts,
                        "top_k": top_k,
                    },
                )
                response.raise_for_status()
                results = response.json()["results"]

            reranked = [chunks[i] for i in results]
            logger.info(f"[Reranker] 重排序完成, 返回{len(reranked)}条")
            return reranked[:top_k]

        except Exception as e:
            logger.warning(f"Rerank failed: {e}, returning original chunks")
            if raise_on_failure:
                raise RuntimeError(f"rerank_request_failed: {e}") from e
            return chunks[:top_k]


class LocalReranker:
    """Local reranker using sentence-transformers."""

    def __init__(self, model_name: str = "BAAI/bge-reranker-base"):
        """Initialize local reranker.

        Args:
            model_name: ModelScope model name
        """
        try:
            from modelscope import snapshot_download
            from sentence_transformers import CrossEncoder
            
            # 使用ModelScope下载模型
            model_dir = snapshot_download(model_name, cache_dir='/root/.cache/modelscope')
            self.model = CrossEncoder(model_dir)
            self.use_local = True
        except Exception as e:
            logger.warning(f"Failed to load reranker model: {e}")
            self.use_local = False

    def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_k: int = 5,
    ) -> list[dict]:
        """Re-rank chunks locally.

        Args:
            query: Query text
            chunks: List of chunk dicts
            top_k: Number of results

        Returns:
            Re-ranked chunks
        """
        if not chunks:
            return []

        if not self.use_local:
            return chunks[:top_k]

        texts = [chunk["content"] for chunk in chunks]
        pairs = [[query, text] for text in texts]

        scores = self.model.predict(pairs)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        reranked = [chunks[i] for i in ranked_indices]
        return reranked[:top_k]
