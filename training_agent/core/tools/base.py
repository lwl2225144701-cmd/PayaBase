"""Base Tool Interface.

Abstract base class for all agent tools.
"""

import inspect
from abc import ABC, abstractmethod


class BaseTool(ABC):
    """Abstract base class for agent tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Tool name (unique, snake_case)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Tool description for LLM."""
        ...

    @abstractmethod
    def get_definition(self) -> dict:
        """Return OpenAI function calling schema."""
        ...

    @abstractmethod
    def invoke(self, **kwargs) -> str:
        """Execute the tool, return string result for LLM."""
        ...

    async def ainvoke(self, **kwargs) -> str:
        """Async execution entrypoint.

        Default behavior wraps the synchronous invoke for compatibility.
        """
        result = self.invoke(**kwargs)
        if inspect.isawaitable(result):
            return await result
        return result
