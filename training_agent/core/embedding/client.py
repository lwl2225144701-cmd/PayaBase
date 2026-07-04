"""Embedding Client.

Client for vector service or Ollama.
"""

from typing import Optional
import logging
import asyncio

import httpx
import requests

from core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingClient:
    """Vector service client."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        """Initialize client.

        Args:
            base_url: Vector service URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or settings.vector_service_url
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async client.

        Returns:
            httpx AsyncClient
        """
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
            )
        return self._client

    async def close(self):
        """Close client connection."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using vector service (优先) or Ollama.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        logger.info(f"[Embedding] 请求向量化, texts={len(texts)}, first_text={texts[0][:30] if texts else ''}...")
        
        # 优先使用vector-service
        try:
            client = await self._get_client()
            response = await client.post(
                "/embed",
                json={"texts": texts},
            )
            response.raise_for_status()
            data = response.json()
            embeddings = data.get("embeddings", [])
            logger.info(f"[Embedding] vector-service响应成功, embeddings={len(embeddings)}, dim={len(embeddings[0]) if embeddings else 0}")
            return embeddings
        except Exception as e:
            logger.warning(f"[Embedding] vector-service失败: {e}, 尝试Ollama")
        
        # Fallback to Ollama
        if settings.llm_provider == "ollama":
            embeddings = []
            for text in texts:
                resp = await asyncio.to_thread(
                    requests.post,
                    f"{settings.llm_base_url}/api/embeddings",
                    json={"model": settings.llm_model, "prompt": text},
                    timeout=60,
                )
                embeddings.append(resp.json().get("embedding", []))
            logger.info(f"[Embedding] Ollama响应成功, embeddings={len(embeddings)}")
            return embeddings

        client = await self._get_client()

        response = await client.post(
            "/embed",
            json={"texts": texts},
        )
        response.raise_for_status()

        data = response.json()
        return data.get("embeddings", [])

    async def embed_single(self, text: str) -> list[float]:
        """Embed single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        embeddings = await self.embed([text])
        return embeddings[0] if embeddings else []

    async def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Embed texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Batch size

        Returns:
            List of embedding vectors
        """
        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = await self.embed(batch)
            results.extend(embeddings)

        return results


class SyncEmbeddingClient:
    """Synchronous embedding client for sync operations."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        timeout: float = 60.0,
    ):
        """Initialize client.

        Args:
            base_url: Vector service URL
            timeout: Request timeout in seconds
        """
        self.base_url = base_url or settings.vector_service_url
        self.timeout = timeout

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using vector service (优先) or Ollama.

        Args:
            texts: List of texts to embed

        Returns:
            List of embedding vectors
        """
        logger.info(f"[SyncEmbedding] 请求向量化, texts={len(texts)}, first_text={texts[0][:30] if texts else ''}...")
        
        # 优先使用vector-service
        try:
            with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
                response = client.post(
                    "/embed",
                    json={"texts": texts},
                )
                response.raise_for_status()
                data = response.json()
                embeddings = data.get("embeddings", [])
                logger.info(f"[SyncEmbedding] vector-service响应成功, embeddings={len(embeddings)}, dim={len(embeddings[0]) if embeddings else 0}")
                return embeddings
        except Exception as e:
            logger.warning(f"[SyncEmbedding] vector-service失败: {e}, 尝试Ollama")
        
        # Fallback to Ollama
        if settings.llm_provider == "ollama":
            embeddings = []
            for text in texts:
                resp = requests.post(
                    f"{settings.llm_base_url}/api/embeddings",
                    json={"model": settings.llm_model, "prompt": text},
                    timeout=60,
                )
                embeddings.append(resp.json().get("embedding", []))
            logger.info(f"[SyncEmbedding] Ollama响应成功, embeddings={len(embeddings)}")
            return embeddings

        with httpx.Client(base_url=self.base_url, timeout=self.timeout) as client:
            response = client.post(
                "/embed",
                json={"texts": texts},
            )
            response.raise_for_status()

            data = response.json()
            return data.get("embeddings", [])

    def embed_single(self, text: str) -> list[float]:
        """Embed single text.

        Args:
            text: Text to embed

        Returns:
            Embedding vector
        """
        embeddings = self.embed([text])
        return embeddings[0] if embeddings else []

    def embed_batch(
        self,
        texts: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Embed texts in batches.

        Args:
            texts: List of texts to embed
            batch_size: Batch size

        Returns:
            List of embedding vectors
        """
        results = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            embeddings = self.embed(batch)
            results.extend(embeddings)

        return results
