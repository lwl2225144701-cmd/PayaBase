"""PDF Export Tool.

T07 - 提交 PDF 生成异步任务，返回 task_id。
"""

import json
import logging
import uuid

from core.tools.base import BaseTool

logger = logging.getLogger(__name__)


class PDFExportTool(BaseTool):
    """T07 - PDF export tool. Submits Celery task, returns task_id."""

    def __init__(self, tenant_id: str):
        self._tenant_id = tenant_id

    @property
    def name(self) -> str:
        return "pdf_export"

    @property
    def description(self) -> str:
        return (
            "将方案内容导出为 PDF 文档。"
            "输入 Markdown 格式的内容，后台异步生成 PDF。"
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
                            "description": "要导出的内容（Markdown 格式）",
                        },
                        "title": {
                            "type": "string",
                            "description": "文档标题",
                        },
                    },
                    "required": ["content"],
                },
            },
        }

    def invoke(self, content: str, title: str = "方案", **kwargs) -> str:
        task_id = str(uuid.uuid4())
        try:
            from core.tasks.pdf_generation import generate_pdf_task
            from sqlalchemy import create_engine, text
            from core.config import settings

            engine = create_engine(settings.sync_database_url)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO pdf_tasks (id, tenant_id, title, status, progress, created_at)
                        VALUES (:id, :tenant_id, :title, 'pending', 0, NOW())
                    """),
                    {
                        "id": task_id,
                        "tenant_id": self._tenant_id,
                        "title": title[:200],
                    },
                )
            engine.dispose()

            generate_pdf_task.delay(
                task_id=task_id,
                title=title[:200],
                content=content,
                tenant_id=self._tenant_id,
            )

            logger.info(f"[PDFExportTool] Task submitted: {task_id}")
            return json.dumps({
                "task_id": task_id,
                "message": f"PDF「{title}」正在后台生成，请稍候...",
                "status": "pending",
            }, ensure_ascii=False)

        except Exception as e:
            logger.error(f"[PDFExportTool] Failed: {e}", exc_info=True)
            self._mark_failed(task_id, str(e))
            return json.dumps({
                "task_id": task_id,
                "error": f"PDF 生成任务提交失败: {str(e)}",
            }, ensure_ascii=False)

    @staticmethod
    def _mark_failed(task_id: str, error: str):
        try:
            from sqlalchemy import create_engine, text
            from core.config import settings
            engine = create_engine(settings.sync_database_url)
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        UPDATE pdf_tasks
                        SET status='failed', error_message=:err, completed_at=NOW()
                        WHERE id=:id
                    """),
                    {"id": task_id, "err": error[:500]},
                )
            engine.dispose()
        except Exception as inner:
            logger.warning(f"[PDFExportTool] Failed to mark task failed: {inner}")
