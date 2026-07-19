"""Reranker.

bge-rerank for result re-ranking.
"""

import logging
import math
from typing import Optional

import httpx

from core.config import settings

logger = logging.getLogger(__name__)


def _sigmoid(x: float) -> float:
    """把 cross-encoder 原始 logits 归一化到 (0, 1)。

    bge-reranker 直接 predict 出来的是无界 logits(可为负、可远大于 1),
    不能直接当作相关度百分比或用于 threshold 过滤。sigmoid 是单调变换,
    保序且落到 (0,1), 使 rerank_score 既可用于 threshold 也可显示为百分比。
    """
    try:
        return 1.0 / (1.0 + math.exp(-x))
    except OverflowError:
        return 1.0 if x > 0 else 0.0


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

        返回按重排后顺序排列的列表, 每个元素为
        ``{"index": <输入序号>, "rerank_score": <归一化到 [0,1] 的相关度>}``。

        注意:
        - 用「输入 index」映射回候选块, **不再用 content 文本匹配**(不同块正文可能相同/
          被截断/清洗, 文本匹配不可靠)。
        - score 经 sigmoid 归一化到 (0,1), 才能用于 threshold 过滤与百分比展示。
        - rerank_score 为 None 表示该结果不可用(服务未返回分数/分数非法), 由调用方跳过。

        Args:
            query: Query text
            chunks: List of chunk dicts
            top_k: Number of results

        Returns:
            重排后的 [{"index": int, "rerank_score": float | None}, ...]
        """
        if not chunks:
            return []

        logger.info(f"[Reranker] 请求重排序, query={query[:30]}, chunks={len(chunks)}, top_k={top_k}")

        texts = [chunk["content"] for chunk in chunks]

        try:
            with httpx.Client(timeout=30.0, trust_env=False) as client:
                response = client.post(
                    f"{self.base_url}/rerank",
                    json={
                        "query": query,
                        "texts": texts,
                        "top_k": top_k,
                    },
                )
                response.raise_for_status()
                data = response.json()
                indices = data.get("results") or []
                raw_scores = data.get("scores") or []

            out: list[dict] = []
            for j, idx in enumerate(indices):
                try:
                    raw = float(raw_scores[j]) if j < len(raw_scores) else None
                except (TypeError, ValueError):
                    raw = None
                norm = _sigmoid(raw) if raw is not None else None
                out.append({"index": int(idx), "rerank_score": norm})
            logger.info(f"[Reranker] 重排序完成, 返回{len(out)}条")
            return out[:top_k]

        except Exception as e:
            logger.warning(f"Rerank failed: {e}, returning original order without scores")
            if raise_on_failure:
                raise RuntimeError(f"rerank_request_failed: {e}") from e
            return [{"index": i, "rerank_score": None} for i in range(len(chunks))]


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
            return [{"index": i, "rerank_score": None} for i in range(len(chunks))]

        texts = [chunk["content"] for chunk in chunks]
        pairs = [[query, text] for text in texts]

        scores = self.model.predict(pairs)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)

        out = []
        for i in ranked_indices[:top_k]:
            out.append({"index": i, "rerank_score": _sigmoid(float(scores[i]))})
        return out
