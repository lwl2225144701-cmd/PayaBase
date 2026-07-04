"""FunctionCall Router (Simplified).

Since Ollama function calling may not work reliably with all models,
this implementation uses a prompt-based approach:
1. LLM classifies which KB to query
2. Retrieve from selected KB
3. Generate answer

This achieves the same goal: LLM decides which knowledge base to use.
"""

import logging
from typing import Generator

from core.llm.factory import get_llm_client
from core.tools.dataset_tool import DatasetTool
from core.prompts.agent import ROUTER_CLASSIFY_PROMPT, ROUTER_SYSTEM_PROMPT, ROUTER_FALLBACK_PROMPT

logger = logging.getLogger(__name__)


class FunctionCallRouter:
    """Multi-dataset router using prompt-based classification.

    Step 1: LLM classifies which KB the question relates to
    Step 2: Retrieve from that KB
    Step 3: Generate answer with context
    """

    CLASSIFY_PROMPT = ROUTER_CLASSIFY_PROMPT

    def __init__(self, kbs: list[dict]):
        """Initialize router.

        Args:
            kbs: List of {id, name} dicts
        """
        self.kbs = kbs
        self.tools = {}
        for kb in kbs:
            tool_name = self._to_tool_name(kb["name"])
            self.tools[tool_name] = DatasetTool(
                kb_id=kb["id"],
                kb_name=tool_name,
                kb_description=f"从 {kb['name']} 中检索信息",
            )

    def _to_tool_name(self, name: str) -> str:
        return name.lower().replace(" ", "-").replace("_", "-")[:50]

    def run(
        self,
        query: str,
        history: list[dict],
        top_k: int = 5,
    ) -> Generator[str, None, None]:
        """Run the router.

        Args:
            query: User query
            history: Message history
            top_k: Retrieval results

        Yields:
            Response chunks
        """
        if not self.kbs:
            yield from self._direct_answer(query, history)
            return

        # Step 1: Classify which KB to use
        target_kb = self._classify_kb(query)

        if target_kb == "none" or target_kb is None:
            yield from self._direct_answer(query, history)
            return

        # Step 2: Retrieve from the target KB
        tool = self.tools.get(target_kb)
        if not tool:
            yield from self._direct_answer(query, history)
            return

        yield from self._stream("[检索知识库中]...")

        retrieval_result = tool.invoke(query, top_k=top_k)

        # Step 3: Generate answer with context
        context_parts = []
        for i, line in enumerate(retrieval_result.split("\n\n"), 1):
            if line.strip():
                context_parts.append(line)
        context = "\n\n".join(context_parts) if context_parts else retrieval_result

        system_prompt = ROUTER_SYSTEM_PROMPT.format(context=context)

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})

        llm = get_llm_client("chat")
        try:
            for chunk in llm.stream_chat(messages):
                yield chunk
        except Exception as e:
            logger.error(f"LLM streaming failed: {e}")
            yield "抱歉，服务暂时不可用。"

    def _classify_kb(self, query: str) -> str:
        """Classify which KB the query relates to."""
        if not self.kbs:
            return "none"

        kb_list = "\n".join([f"- {t_name}: {t.kb_description}" for t_name, t in self.tools.items()])
        prompt = self.CLASSIFY_PROMPT.format(kb_list=kb_list, query=query)

        # 统一走工厂:业务层不关心 provider / base_url / model
        try:
            llm = get_llm_client("classify")
            answer = llm.chat(
                [{"role": "user", "content": prompt}],
                stream=False,
                temperature=0,
            ).strip()

            for t_name in self.tools:
                if t_name in answer.lower():
                    return t_name
                if t_name.replace("-", " ") in answer.lower():
                    return t_name

            for t_name, tool in self.tools.items():
                kb_name_normalized = t_name.replace("-", " ")
                if kb_name_normalized in answer.lower():
                    return t_name

            return "none"
        except Exception as e:
            logger.warning(f"KB classification failed: {e}")
            return "none"

    def _direct_answer(
        self, query: str, history: list[dict]
    ) -> Generator[str, None, None]:
        messages = [
            {"role": "system", "content": ROUTER_FALLBACK_PROMPT}
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": query})

        llm = get_llm_client("chat")
        try:
            for chunk in llm.stream_chat(messages):
                yield chunk
        except Exception as e:
            yield "抱歉，服务暂时不可用。"

    def _stream(self, content: str) -> Generator[str, None, None]:
        for char in content:
            yield char