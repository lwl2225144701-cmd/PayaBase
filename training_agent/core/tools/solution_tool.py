"""Solution Generator Tool.

Generates structured Markdown solutions from context.
"""

import logging

from core.tools.base import BaseTool
from core.llm.client import LLMClient

logger = logging.getLogger(__name__)

SOLUTION_PROMPT = """你是一个方案生成专家。基于以下检索到的参考资料，为用户生成结构化的解决方案。

【参考资料】
{context}

【输出格式要求】
## 结论
简明扼要的核心结论（2-3句话）

## 分析维度
从不同角度分析问题（每个维度包含小标题和说明）

## 行动建议
具体的、可执行的建议步骤（编号列表）

## 来源引用
标注信息来源，格式：[文档名]

【要求】
- 严格基于参考资料，禁止编造
- 资料不足的部分明确标注"资料不足，建议进一步确认"
- 语言专业、简洁"""


class SolutionGeneratorTool(BaseTool):
    """Generate structured Markdown solutions from retrieved context."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    @property
    def name(self) -> str:
        return "solution_generator"

    @property
    def description(self) -> str:
        return (
            "基于已检索的参考资料，生成结构化的解决方案。"
            "包含：结论、分析维度、行动建议、来源引用。"
            "当已经通过 knowledge_retrieval 获取到足够信息后调用此工具。"
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
                            "description": "用户的原始问题",
                        },
                        "context": {
                            "type": "string",
                            "description": "已检索到的参考资料内容",
                        },
                    },
                    "required": ["query", "context"],
                },
            },
        }

    def invoke(self, query: str, context: str, **kwargs) -> str:
        try:
            prompt = SOLUTION_PROMPT.format(context=context)
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": query},
            ]
            result = self._llm.chat(messages, stream=False, temperature=0.3)
            return result
        except Exception as e:
            logger.error(f"[SolutionGeneratorTool] Generation failed: {e}")
            return f"方案生成失败: {str(e)}"
