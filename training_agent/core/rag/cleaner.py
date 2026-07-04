import re
from typing import Optional

from langchain_core.documents import Document


class CleanProcessor:
    """文本清洗处理器"""

    def __init__(self, process_rule: Optional[dict] = None):
        """
        Args:
            process_rule: 清洗规则配置
                {
                    "remove_extra_spaces": True/False,
                    "remove_urls_emails": True/False
                }
        """
        self.process_rule = process_rule or {
            "remove_extra_spaces": True,
            "remove_urls_emails": False,
        }

    def clean(self, documents: list[Document]) -> list[Document]:
        """清洗文档

        Args:
            documents: 原始文档列表

        Returns:
            清洗后的文档列表
        """
        for doc in documents:
            doc.page_content = self._clean_text(doc.page_content)
        return documents

    def _clean_text(self, text: str) -> str:
        """清洗文本"""
        text = self._default_clean(text)
        text = self._optional_clean(text)
        return text.strip()

    def _default_clean(self, text: str) -> str:
        """默认清洗规则（始终生效）"""
        text = re.sub(r"<\|", "<", text)
        text = re.sub(r"\|>", ">", text)

        text = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F\xEF\xBF\xBE]", "", text)

        text = re.sub("\ufffe", "", text)

        return text

    def _optional_clean(self, text: str) -> str:
        """可选清洗规则"""
        if self.process_rule.get("remove_extra_spaces"):
            text = self._remove_extra_spaces(text)

        if self.process_rule.get("remove_urls_emails"):
            text = self._remove_urls_emails(text)

        return text

    def _remove_extra_spaces(self, text: str) -> str:
        """移除多余空格"""
        text = re.sub(r"\n{3,}", "\n\n", text)

        text = re.sub(
            r"[\t\f\r\x20\u00a0\u1680\u180e\u2000-\u200a\u202f\u205f\u3000]{2,}",
            " ",
            text,
        )

        return text

    def _remove_urls_emails(self, text: str) -> str:
        """移除URL和邮箱"""
        markdown_placeholders = {}

        def protect_link(m):
            key = f"__MARKDOWN_LINK_{len(markdown_placeholders)}__"
            markdown_placeholders[key] = m.group(0)
            return key

        text = re.sub(r"\[([^\]]+)\]\(https?://[^\)]+\)", protect_link, text)

        def protect_image(m):
            key = f"__MARKDOWN_IMAGE_{len(markdown_placeholders)}__"
            markdown_placeholders[key] = m.group(0)
            return key

        text = re.sub(r"!\[([^\]]*)\]\(https?://[^\)]+\)", protect_image, text)

        text = re.sub(
            r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+", "", text
        )
        text = re.sub(r"https?://\S+", "", text)

        for key, value in markdown_placeholders.items():
            text = text.replace(key, value)

        return text