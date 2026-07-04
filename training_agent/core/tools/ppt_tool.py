"""PPT Generation Tool.

T06 - 提交 PPT 生成异步任务，返回 task_id。
"""

import json
import logging
import uuid

from core.tools.base import BaseTool

logger = logging.getLogger(__name__)


class PPTGenerationTool(BaseTool):
    """T06 - PPT generation tool. Submits Celery task, returns task_id."""

    def __init__(self, tenant_id: str):
        self._tenant_id = tenant_id

    @property
    def name(self) -> str:
        return "ppt_generation"

    @property
    def description(self) -> str:
        return (
            "根据培训方案内容生成PPT演示文稿。"
            "输入方案的Markdown内容和标题，后台异步生成PPT。"
            "返回任务ID，用户可通过任务ID查询进度和下载。"
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
                            "description": "方案内容（Markdown格式）",
                        },
                        "title": {
                            "type": "string",
                            "description": "PPT标题",
                        },
                    },
                    "required": ["content"],
                },
            },
        }

    def invoke(self, content: str, title: str = "培训方案", **kwargs) -> str:
        task_id = str(uuid.uuid4())
        try:
            from core.tasks.ppt_generation import generate_ppt_task
            from sqlalchemy import create_engine, text
            from core.config import settings

            engine = create_engine(settings.sync_database_url)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO ppt_tasks (id, tenant_id, title, status, progress, created_at)
                        VALUES (:id, :tenant_id, :title, 'pending', 0, NOW())
                    """),
                    {
                        "id": task_id,
                        "tenant_id": self._tenant_id,
                        "title": title[:200],
                    },
                )
            engine.dispose()

            generate_ppt_task.delay(
                task_id=task_id,
                title=title[:200],
                content=content,
                tenant_id=self._tenant_id,
            )

            logger.info(f"[PPTGenerationTool] Task submitted: {task_id}")
            return json.dumps({
                "task_id": task_id,
                "message": f"PPT「{title}」正在后台生成，请稍候...",
                "status": "pending",
            }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"[PPTGenerationTool] Failed: {e}", exc_info=True)
            self._mark_failed(task_id, str(e))
            return json.dumps({
                "task_id": task_id,
                "error": f"PPT 生成任务提交失败: {str(e)}",
            }, ensure_ascii=False)

    @staticmethod
    def _mark_failed(task_id: str, error: str):
        """Best-effort: mark task as failed in DB."""
        try:
            from sqlalchemy import create_engine, text
            from core.config import settings
            engine = create_engine(settings.sync_database_url)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE ppt_tasks
                        SET status='failed', error_message=:err, completed_at=NOW()
                        WHERE id=:id
                    """),
                    {"id": task_id, "err": error[:500]},
                )
            engine.dispose()
        except Exception as inner:
            logger.warning(f"[PPTGenerationTool] Failed to mark task failed: {inner}")
