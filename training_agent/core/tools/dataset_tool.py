"""Dataset Tool.

Each knowledge base becomes a retrievable tool.
"""

import concurrent.futures
from typing import Optional

from core.config import settings


class DatasetTool:
    """A knowledge base as an LLM tool.

    This tool allows the LLM to retrieve relevant information from a specific
    knowledge base when needed.
    """

    def __init__(self, kb_id: str, kb_name: str, kb_description: str = ""):
        """Initialize dataset tool.

        Args:
            kb_id: Knowledge base ID
            kb_name: Tool name (kebab-case)
            kb_description: Tool description for LLM
        """
        self.kb_id = kb_id
        self.kb_name = kb_name
        self.kb_description = kb_description or f"从知识库 {kb_name} 中检索相关信息来回答用户问题"

    def get_tool_definition(self, tool_name: Optional[str] = None) -> dict:
        """Get OpenAI-style tool definition."""
        name = tool_name or self.kb_name
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": self.kb_description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "检索查询关键词，从知识库中查找相关信息",
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def invoke(self, query: str, top_k: int = 5, threshold: float = 0.3) -> str:
        """Invoke the tool - retrieve from knowledge base.

        Uses ThreadPoolExecutor to avoid event loop issues.

        Args:
            query: Search query
            top_k: Number of results
            threshold: Similarity threshold

        Returns:
            Formatted retrieval results
        """
        def _sync_invoke():
            import requests

            try:
                emb_resp = requests.post(
                    f"{settings.llm_base_url}/api/embeddings",
                    json={"model": settings.llm_model, "prompt": query},
                    timeout=60,
                )
                query_vec = emb_resp.json().get("embedding", [])
            except:
                return "检索服务暂时不可用"

            if not query_vec:
                return "无法生成查询向量"

            from sqlalchemy import create_engine, text
            engine = create_engine(settings.sync_database_url)
            with engine.connect() as conn:
                result = conn.execute(text("""
                    SELECT c.id, c.content, c.vector, d.title
                    FROM chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE d.knowledge_base_id = :kb_id
                    AND c.vector IS NOT NULL
                    AND c.vector != '[]'
                """), {"kb_id": self.kb_id})
                rows = result.mappings().all()

            engine.dispose()

            def parse_vec(s):
                try:
                    s = str(s).strip()
                    if s.startswith("["):
                        nums = s[1:-1].split(",")
                        return [float(x.strip()) for x in nums]
                except:
                    pass
                return None

            def cosine_sim(a, b):
                if not a or not b or len(a) != len(b):
                    return 0
                dot = sum(x * y for x, y in zip(a, b))
                norm_a = sum(x * x for x in a) ** 0.5
                norm_b = sum(x * x for x in b) ** 0.5
                if norm_a == 0 or norm_b == 0:
                    return 0
                return dot / (norm_a * norm_b)

            scored = []
            for row in rows:
                vec = parse_vec(row.get("vector", ""))
                if vec:
                    sim = cosine_sim(query_vec, vec)
                    if sim >= threshold:
                        scored.append((row, sim))

            scored.sort(key=lambda x: x[1], reverse=True)
            scored = scored[:top_k]

            if not scored:
                return "未找到相关信息"

            parts = []
            for i, (row, score) in enumerate(scored, 1):
                content = row["content"][:500]
                parts.append(f"【{i}】{row['title']}\n{content}\n(相似度: {score:.2f})")

            return "\n\n".join(parts)

        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(_sync_invoke)
            return future.result(timeout=60)