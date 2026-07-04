"""Knowledge Retrieval Tool.

Wraps existing RAG retrieval for agent tool calling.
"""

import logging

from core.tools.base import BaseTool

logger = logging.getLogger(__name__)


class KnowledgeRetrievalTool(BaseTool):
    """Retrieve relevant information from a knowledge base."""

    def __init__(self, kb_id: str, kb_name: str, top_k: int = 5):
        self._kb_id = kb_id
        self._kb_name = kb_name
        self._top_k = top_k

    @property
    def name(self) -> str:
        return "knowledge_retrieval"

    @property
    def description(self) -> str:
        return (
            f"从知识库「{self._kb_name}」中检索与查询相关的文档片段。"
            f"当需要查找资料、制度、流程、技术文档等信息时使用此工具。"
        )

    def get_definition(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "检索查询关键词，描述需要查找的信息",
                        },
                        "top_k": {
                            "type": "integer",
                            "description": "返回结果数量，默认5",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def invoke(self, query: str, top_k: int = 5, **kwargs) -> str:
        return "知识库检索工具需要在异步执行链中调用。"

    async def ainvoke(self, query: str, top_k: int = 5, **kwargs) -> str:
        return await self._async_invoke(query, top_k)

    async def _async_invoke(self, query: str, top_k: int) -> str:
        from core.embedding.client import EmbeddingClient
        from core.rag.retriever import Retriever
        from models.db import async_session

        try:
            embedding_client = EmbeddingClient()
            query_vector = await embedding_client.embed_single(query)
            if not query_vector:
                return "无法生成查询向量，请检查向量服务是否可用。"

            async with async_session() as session:
                retriever = Retriever(session)
                chunks = await retriever.similarity_search(
                    query_vector=query_vector,
                    kb_id=self._kb_id,
                    top_k=top_k,
                    threshold=0.2,
                    query_text=query,
                    use_rerank=True,
                )

                if not chunks:
                    return "未在知识库中找到相关信息。"

                parts = []
                for i, chunk in enumerate(chunks, 1):
                    content = chunk.content[:500]
                    source = chunk.document_title
                    score = chunk.score
                    parts.append(
                        f"【{i}】[{source}] (相关度: {score:.2f})\n{content}"
                    )

                return "\n\n".join(parts)

        except Exception as e:
            logger.error(f"[KnowledgeRetrievalTool] Retrieval failed: {e}")
            return f"检索失败: {str(e)}"
