"""Task-profile selection (应用层门面)。

逻辑已下沉到 `core/domain/agent/strategy.py`。本模块仅做再导出，
保持 `from core.agent.strategy import select_task_profile, TaskProfile` 兼容。
"""

from __future__ import annotations

from core.domain.agent.strategy import TaskProfile, select_task_profile

__all__ = ["TaskProfile", "select_task_profile"]
