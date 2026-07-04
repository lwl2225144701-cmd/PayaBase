"""Resume Extraction Tool.

T04 - 从简历文本中提取结构化信息。
"""

import json
import logging

from core.tools.base import BaseTool
from core.llm.client import LLMClient

logger = logging.getLogger(__name__)

EXTRACT_PROMPT = """你是一个简历信息抽取专家。从以下简历文本中提取结构化信息。

【简历文本】
{content}

【输出要求】
严格输出 JSON，不要有其他文字。格式如下：

{{
  "name": "姓名",
  "current_role": "当前职位/身份",
  "education": [
    {{"school": "学校", "degree": "学位", "major": "专业", "year": "毕业年份"}}
  ],
  "work_experience": [
    {{"company": "公司", "role": "职位", "duration": "时间段", "highlights": "核心成就"}}
  ],
  "skills": ["技能1", "技能2", "技能3"],
  "target": "求职目标或发展方向",
  "summary": "一句话总结"
}}

【规则】
- 提取所有能识别的信息，缺失字段填 null
- skills 提取技术栈、工具、语言等
- 保持原文信息，不要推测"""


class ResumeExtractionTool(BaseTool):
    """Extract structured information from resume text."""

    def __init__(self, llm_client: LLMClient):
        self._llm = llm_client

    @property
    def name(self) -> str:
        return "resume_extraction"

    @property
    def description(self) -> str:
        return (
            "从简历或个人背景描述中提取结构化信息，"
            "包括：姓名、教育背景、工作经历、技能、求职目标。"
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
                        "content": {
                            "type": "string",
                            "description": "简历或个人背景的文本内容",
                        },
                    },
                    "required": ["content"],
                },
            },
        }

    def invoke(self, content: str, **kwargs) -> str:
        try:
            prompt = EXTRACT_PROMPT.format(content=content[:3000])
            messages = [
                {"role": "system", "content": prompt},
                {"role": "user", "content": "请提取简历信息"},
            ]
            result = self._llm.chat(messages, stream=False, temperature=0.1)

            # Validate JSON
            try:
                parsed = json.loads(result.strip().strip("```json").strip("```"))
                return json.dumps(parsed, ensure_ascii=False, indent=2)
            except json.JSONDecodeError:
                return result

        except Exception as e:
            logger.error(f"[ResumeExtractionTool] Failed: {e}")
            return f"简历提取失败: {str(e)}"
