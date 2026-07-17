"""Celery PDF Generation Task.

Renders Markdown → PDF → uploads to MinIO → updates status.
"""

import logging
import os
import tempfile
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from core.config import settings
from core.tasks import celery_app

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_pdf_status(
    task_id: str,
    status: str,
    progress: int = 0,
    file_path: Optional[str] = None,
    error_message: Optional[str] = None,
):
    """Update PDF task status in database."""
    engine = create_engine(settings.sync_database_url)
    with Session(engine) as db:
        db.execute(
            text("""
                UPDATE pdf_tasks
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


def _register_cjk_font(pdf) -> bool:
    font_candidates = [
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for font_path in font_candidates:
        if not os.path.exists(font_path):
            continue
        try:
            pdf.add_font("CJK", "", font_path, uni=True)
            pdf.add_font("CJK", "B", font_path, uni=True)
            pdf.add_font("CJK", "I", font_path, uni=True)
            pdf.add_font("CJK", "BI", font_path, uni=True)
            pdf.set_font("CJK", size=12)
            return True
        except Exception:
            continue
    return False


def upload_to_minio(local_path: str, task_id: str) -> str:
    """Upload file to MinIO and return the object key."""
    from core.infrastructure.minio.client import get_minio_client

    minio_client = get_minio_client()

    bucket = settings.pdf_minio_bucket
    if not minio_client.bucket_exists(bucket):
        minio_client.make_bucket(bucket)

    object_key = f"{task_id}/{local_path.rsplit('/', 1)[-1]}"
    minio_client.fput_object(bucket, object_key, local_path)

    logger.info(f"[PDF] Uploaded to MinIO: {bucket}/{object_key}")
    return object_key


@celery_app.task(bind=True, max_retries=2, time_limit=300, soft_time_limit=270)
def generate_pdf_task(self, task_id: str, title: str, content: str, tenant_id: str):
    """Celery task: Generate PDF from Markdown content.

    Steps:
        1. Render Markdown → HTML → PDF (20% → 70%)
        2. Upload to MinIO (70% → 90%)
        3. Update status to ready (100%)
    """
    start_time = time.time()
    local_path = None
    logger.info(f"[PDF] Starting generation: task_id={task_id}, title={title}")

    try:
        update_pdf_status(task_id, "generating", progress=10)

        # Render PDF
        import markdown
        from fpdf import FPDF

        update_pdf_status(task_id, "generating", progress=20)

        html_body = markdown.markdown(
            content,
            extensions=["tables", "fenced_code"],
        )

        html_content = f"""<html><head><meta charset="utf-8"></head><body>
<h1>{title}</h1>
{html_body}
<hr/>
<p style="font-size:10px;color:#999;">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
</body></html>"""

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=20)
        pdf.add_page()

        font_added = _register_cjk_font(pdf)
        if not font_added:
            if any(ord(ch) > 127 for ch in html_content):
                raise RuntimeError("未找到可用的中文字体，无法生成包含中文的 PDF")
            pdf.set_font("Helvetica", size=12)

        pdf.write_html(html_content)

        update_pdf_status(task_id, "generating", progress=60)

        # Save to temp file
        fd, local_path = tempfile.mkstemp(suffix=".pdf", prefix="pdf_gen_")
        os.close(fd)
        pdf.output(local_path)

        update_pdf_status(task_id, "generating", progress=70)

        # Upload to MinIO
        update_pdf_status(task_id, "uploading", progress=80)
        object_key = upload_to_minio(local_path, task_id)

        # Done
        update_pdf_status(task_id, "ready", progress=100, file_path=object_key)

        cost = time.time() - start_time
        logger.info(f"[PDF] Done! task_id={task_id}, cost={cost:.1f}s")

        return {
            "status": "success",
            "task_id": task_id,
            "file_path": object_key,
            "cost_time": cost,
        }

    except Exception as e:
        error_msg = str(e)
        logger.error(f"[PDF] Failed: task_id={task_id}, error={error_msg}", exc_info=True)

        if self.request.retries < 2:
            logger.info(f"[PDF] Retrying... (attempt {self.request.retries + 1})")
            raise self.retry(exc=e, countdown=15)

        update_pdf_status(task_id, "failed", error_message=error_msg)
        return {"status": "error", "task_id": task_id, "message": error_msg}

    finally:
        if local_path:
            try:
                os.unlink(local_path)
            except OSError:
                pass
