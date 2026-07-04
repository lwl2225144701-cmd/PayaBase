"""ReAct Agent Executor.

Multi-tool ReAct reasoning executor using ToolRegistry.
"""

import json
import logging
from typing import AsyncGenerator

from core.llm.client import LLMClient
from core.tools.registry import ToolRegistry
from core.prompts.agent import SOLUTION_AGENT_PROMPT

logger = logging.getLogger(__name__)


class AgentStepExecutor:
    """Step-level multi-tool reasoning executor."""

    def __init__(
        self,
        llm_client: LLMClient,
        registry: ToolRegistry,
        system_prompt: str = SOLUTION_AGENT_PROMPT,
        max_iterations: int = 10,
    ):
        self.llm = llm_client
        self.registry = registry
        self.system_prompt = system_prompt
        self.max_iterations = max_iterations
        # Unified artifact list: [{"type": "ppt"|"pdf", "task_id": "..."}]
        self.artifacts: list[dict] = []
        self.tool_trace: list[dict] = []
        # Legacy fields (kept for backward compat, will be removed later)
        self.ppt_task_id: str | None = None
        self.pdf_task_id: str | None = None

    async def run(
        self,
        query: str,
        history: list[dict],
    ) -> AsyncGenerator[str, None]:
        tools = self.registry.get_all_definitions()
        tool_names = {tool.get("function", {}).get("name") for tool in tools}
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history)
        messages.append({"role": "user", "content": query})
        external_search_needed = False
        external_search_hint_added = False
        web_search_used = False
        forced_web_search_done = False

        # Phase 1: ReAct reasoning loop (non-streaming)
        for iteration in range(self.max_iterations):
            logger.info(f"[AgentStepExecutor] Iteration {iteration + 1}/{self.max_iterations}")

            if external_search_needed and not web_search_used and not external_search_hint_added and "web_search" in tool_names:
                messages.append(
                    {
                        "role": "system",
                        "content": "当前内部资料不足，请优先调用 web_search 补充外部公开信息，再继续生成。不要直接结束。",
                    }
                )
                external_search_hint_added = True

            if (
                external_search_needed
                and not web_search_used
                and not forced_web_search_done
                and "web_search" in tool_names
            ):
                logger.info("[AgentStepExecutor] Forcing web_search follow-up after internal miss")
                forced_result = await self.registry.execute("web_search", {"query": query})
                self.tool_trace.append(
                    {
                        "type": "tool_call",
                        "tool_name": "web_search",
                        "arguments": {"query": query},
                        "status": "forced",
                        "result_preview": forced_result[:500],
                    }
                )
                messages.append({"role": "assistant", "content": "已调用工具: web_search"})
                messages.append({"role": "tool", "tool_call_id": "forced-web-search", "content": forced_result})
                web_search_used = True
                external_search_needed = False
                forced_web_search_done = True
                continue

            request_messages = messages
            if iteration > 0:
                request_messages = self._sanitize_messages_for_followup_tool_round(messages)

            response = self.llm.chat_with_tools(request_messages, tools=tools)
            tool_calls = response.get("tool_calls", [])
            content = response.get("content", "") or ""

            # Normalize tool_calls: OpenAI SDK objects → dicts
            if tool_calls and not isinstance(tool_calls[0], dict):
                tool_calls = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in tool_calls
                ]

            if not tool_calls:
                if external_search_needed and not web_search_used and "web_search" in tool_names:
                    messages.append(
                        {
                            "role": "system",
                            "content": "当前内部资料仍不足，请优先调用 web_search 补充外部公开信息，再继续生成。不要直接结束。",
                        }
                    )
                    external_search_hint_added = True
                    continue
                # No more tools requested -> agent is ready to answer
                if content:
                    messages.append({"role": "assistant", "content": content})
                    yield content
                else:
                    async for chunk in self._stream_final(messages):
                        yield chunk
                return

            # Process tool calls
            logger.info(
                f"[AgentStepExecutor] Tool calls: "
                f"{[tc['function']['name'] for tc in tool_calls]}"
            )

            # Append assistant message with tool_calls
            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": tool_calls,
            })

            # Execute each tool call and append results
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    arguments = json.loads(tc["function"]["arguments"])
                except json.JSONDecodeError:
                    arguments = {}

                logger.info(f"[AgentStepExecutor] Executing tool: {tool_name}, args={arguments}")
                result = await self.registry.execute(tool_name, arguments)
                logger.info(f"[AgentStepExecutor] Tool result ({len(result)} chars): {result[:100]}...")
                tool_status = "error" if result.startswith("Error") or "失败" in result[:40] else "success"
                self.tool_trace.append(
                    {
                        "type": "tool_call",
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "status": tool_status,
                        "result_preview": result[:500],
                    }
                )

                # Track task_ids for frontend progress polling
                if tool_name in ("ppt_generation", "pdf_export"):
                    try:
                        tool_data = json.loads(result)
                        if "task_id" in tool_data:
                            artifact_type = "ppt" if tool_name == "ppt_generation" else "pdf"
                            self.artifacts.append({"type": artifact_type, "task_id": tool_data["task_id"]})
                            # Legacy
                            if artifact_type == "ppt":
                                self.ppt_task_id = tool_data["task_id"]
                            else:
                                self.pdf_task_id = tool_data["task_id"]
                    except (json.JSONDecodeError, TypeError):
                        pass
                if tool_name == "knowledge_retrieval":
                    if any(
                        marker in result
                        for marker in (
                            "未在知识库中找到相关信息",
                            "资料不足",
                            "检索失败",
                            "无法生成查询向量",
                        )
                    ):
                        external_search_needed = True
                if tool_name == "web_search":
                    web_search_used = True
                    external_search_needed = False

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result,
                })

            # Continue the reasoning loop so the agent can decide whether
            # another tool call is needed (for example KB miss -> web search -> export).
            continue

        # Max iterations reached
        logger.warning("[AgentStepExecutor] Max iterations reached")
        yielded = False
        async for chunk in self._stream_final(messages):
            if chunk:
                yielded = True
                yield chunk
        if not yielded:
            yield "抱歉，处理这个问题需要更多时间。请尝试简化您的问题。"

    async def _stream_final(self, messages: list[dict]) -> AsyncGenerator[str, None]:
        try:
            final_messages = self._sanitize_messages_for_final_stream(messages)
            for chunk in self.llm.stream_chat(final_messages, temperature=0.3):
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(f"[AgentStepExecutor] Streaming failed: {e}")
            yield "抱歉，生成回答时出现错误。"

    @staticmethod
    def _sanitize_messages_for_final_stream(messages: list[dict]) -> list[dict]:
        sanitized: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or ""
            if role in {"system", "user"}:
                sanitized.append({"role": role, "content": content})
                continue
            if role == "assistant":
                if content:
                    sanitized.append({"role": "assistant", "content": content})
                tool_calls = msg.get("tool_calls") or []
                if tool_calls:
                    tool_names = []
                    for tc in tool_calls:
                        try:
                            tool_names.append(tc["function"]["name"])
                        except Exception:
                            continue
                    if tool_names:
                        sanitized.append(
                            {
                                "role": "assistant",
                                "content": f"已调用工具: {', '.join(tool_names)}",
                            }
                        )
                continue
            if role == "tool":
                sanitized.append(
                    {
                        "role": "assistant",
                        "content": f"工具返回结果:\n{content}",
                    }
                )
        return sanitized

    @classmethod
    def _sanitize_messages_for_followup_tool_round(cls, messages: list[dict]) -> list[dict]:
        """Prepare messages for providers that reject native tool-role history.

        Keep system/user messages intact and flatten assistant/tool protocol
        messages into plain assistant text so the next tool-decision round can
        continue without sending `role=tool` back to an OpenAI-compatible
        provider that only partially supports the schema.
        """
        return cls._sanitize_messages_for_final_stream(messages)


# Backward compatibility: keep old import path working during migration.
ReActAgent = AgentStepExecutor
