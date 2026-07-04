"""Celery PPT Generation Task.

LLM 生成结构化 slides JSON → python-pptx 构建 → 上传 MinIO → 更新状态。
"""

import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.config import settings
from core.tasks import celery_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_ppt_status(
    task_id: str,
    status: str,
    progress: int = 0,
    file_path: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Update PPT task status in database."""
    engine = create_engine(settings.sync_database_url)
    with Session(engine) as db:
        db.execute(
            text("""
                UPDATE ppt_tasks
                SET status=:status, progress=:progress,
                    file_path=COALESCE(:file_path, file_path),
                    error_message=:error,
                    completed_at=CASE WHEN :status IN ('ready', 'failed') THEN NOW() ELSE completed_at END
                WHERE id=:id
            """),
            {
                "id": task_id,
                "status": status,
                "progress": progress,
                "file_path": file_path,
                "error": error_message,
            },
        )
        db.commit()
    engine.dispose()


def generate_slides_json(title: str, content: str) -> list[dict]:
    """Use LLM to generate structured slides JSON from content."""
    from core.llm.client import LLMClient
    from core.prompts.ppt import PPT_STRUCTURE_PROMPT

    llm = LLMClient(
        api_key=settings.llm_chat_api_key or settings.llm_api_key,
        base_url=settings.llm_chat_base_url or settings.llm_base_url,
        model=settings.llm_chat_model or settings.llm_model,
        api_header_name=settings.llm_chat_api_header_name,
        api_header_prefix=settings.llm_chat_api_header_prefix,
    )

    prompt = PPT_STRUCTURE_PROMPT.format(content=content[:8000])
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": "请将以上内容转换为PPT结构"},
    ]

    result = llm.chat(messages, stream=False, temperature=0.3)

    # Parse JSON from response
    cleaned = result.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    data = json.loads(cleaned)
    slides = data.get("slides", [])

    if not slides:
        raise ValueError("LLM returned empty slides")

    return slides


def upload_to_minio(local_path: str, task_id: str) -> str:
    """Upload file to MinIO and return the object key."""
    from minio import Minio

    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )

    bucket = settings.ppt_minio_bucket
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)

    object_key = f"{task_id}/{local_path.rsplit('/', 1)[-1]}"
    minio_client.fput_object(bucket, object_key, local_path)

    logger.info(f"[PPT] Uploaded to MinIO: {bucket}/{object_key}")
    return object_key


@celery_app.task(bind=True, max_retries=2)
def generate_ppt_task(self, task_id: str, title: str, content: str, tenant_id: str):
    """Celery task: Generate PPT from content.

    Steps:
        1. LLM generates structured slides JSON (10% → 40%)
        2. python-pptx builds .pptx file (40% → 70%)
        3. Upload to MinIO (70% → 90%)
        4. Update status to ready (100%)
    """
    start_time = time.time()
    local_path = None
    logger.info(f"[PPT] Starting generation: task_id={task_id}, title={title}")

    try:
        # Step 1: LLM generates slides structure
        update_ppt_status(task_id, "generating", progress=10)
        logger.info(f"[PPT] Generating slides JSON via LLM...")

        slides = generate_slides_json(title, content)
        logger.info(f"[PPT] LLM generated {len(slides)} slides")

        update_ppt_status(task_id, "generating", progress=40)

        # Step 2: Build .pptx file
        logger.info(f"[PPT] Building .pptx file...")
        from core.tools.pptx_builder import PptxBuilder

        builder = PptxBuilder()
        local_path = builder.build(title, slides)
        logger.info(f"[PPT] Built: {local_path}")

        update_ppt_status(task_id, "generating", progress=70)

        # Step 3: Upload to MinIO
        update_ppt_status(task_id, "uploading", progress=80)
        logger.info(f"[PPT] Uploading to MinIO...")

        object_key = upload_to_minio(local_path, task_id)
        logger.info(f"[PPT] Uploaded: {object_key}")

        # Step 4: Done
        update_ppt_status(task_id, "ready", progress=100, file_path=object_key)

        cost = time.time() - start_time
        logger.info(f"[PPT] Done! task_id={task_id}, slides={len(slides)}, cost={cost:.1f}s")

        return {
            "status": "success",
            "task_id": task_id,
            "slides_count": len(slides),
            "file_path": object_key,
            "cost_time": cost,
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[PPT] Failed: task_id={task_id}, error={error_msg}", exc_info=True)

        if self.request.retries < 2:
            logger.info(f"[PPT] Retrying... (attempt {self.request.retries + 1})")
            raise self.retry(exc=e, countdown=30)

        update_ppt_status(task_id, "failed", error_message=error_msg)
        return {"status": "error", "task_id": task_id, "message": error_msg}

    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:
                pass
