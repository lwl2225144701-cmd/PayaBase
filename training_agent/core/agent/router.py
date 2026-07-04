"""Knowledge Router.

Route to knowledge base based on user/query.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class KnowledgeRouter:
    """Route to knowledge base."""

    KEYWORDS_MAP = {
        "tech": ["技术", "代码", "编程", "开发", "系统", "软件"],
        "hr": ["制度", "请假", "报销", "薪资", "人事", "员工"],
        "product": ["产品", "功能", "使用", "教程"],
        "sales": ["销售", "客户", "业绩", "合同"],
    }

    def __init__(self):
        """Initialize router."""
        pass

    def route(
        self,
        query: str,
        user_department: Optional[str],
        knowledge_bases: list[dict],
    ) -> Optional[str]:
        """Route to knowledge base ID.

        Args:
            query: User query
            user_department: User department code
            knowledge_bases: Available knowledge bases

        Returns:
            Knowledge base ID or None
        """
        if not knowledge_bases:
            return None

        if user_department:
            for kb in knowledge_bases:
                if kb.get("department_id") == user_department:
                    return kb["id"]

        query_lower = query.lower()
        for dept_code, keywords in self.KEYWORDS_MAP.items():
            for keyword in keywords:
                if keyword in query_lower:
                    for kb in knowledge_bases:
                        if kb.get("department_code") == dept_code:
                            return kb["id"]

        return knowledge_bases[0]["id"] if knowledge_bases else None

    def get_default_kb(self, knowledge_bases: list[dict]) -> Optional[str]:
        """Get default knowledge base.

        Args:
            knowledge_bases: Available knowledge bases

        Returns:
            Default knowledge base ID
        """
        return knowledge_bases[0]["id"] if knowledge_bases else None