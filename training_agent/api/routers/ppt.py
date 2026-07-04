"""PPT API Endpoints.

Status polling and file download for PPT generation tasks.
"""

import os
import uuid
import tempfile
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select

from api.deps import DBSession, CurrentUser
from api.schemas.common import Response
from models.tables import PPTTask

logger = logging.getLogger(__name__)

router = APIRouter()


async def _resolve_task(
    task_id: str,
    db,
    user,
) -> PPTTask:
    """Find PPT task by id and tenant."""
    result = await db.execute(
        select(PPTTask).where(
            PPTTask.id == uuid.UUID(task_id),
            PPTTask.tenant_id == uuid.UUID(user.tenant_id),
        )
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="PPT task not found")
    return task


@router.get("/ppt/{task_id}/status")
async def get_ppt_status(
    task_id: str,
    db: DBSession,
    current_user: CurrentUser,
):
    """Get PPT generation task status (for frontend polling)."""
    task = await _resolve_task(task_id, db, current_user)

    return Response(data={
        "id": str(task.id),
        "title": task.title,
        "status": task.status,
        "progress": task.progress,
        "error_message": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
    })


def _cleanup_temp_file(path: str):
    """Best-effort temp file cleanup."""
    try:
        os.unlink(path)
    except OSError:
        pass


@router.get("/ppt/{task_id}/download")
async def download_ppt(
    task_id: str,
    db: DBSession,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
):
    """Download generated PPT file. Authorization header only."""
    task = await _resolve_task(task_id, db, current_user)

    if task.status != "ready" or not task.file_path:
        raise HTTPException(status_code=400, detail="PPT not ready yet")

    from minio import Minio
    from core.config import settings

    minio_client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )

    bucket = settings.ppt_minio_bucket
    # Random temp filename to avoid concurrent download collisions
    fd, tmp_path = tempfile.mkstemp(suffix=".pptx", prefix="ppt_dl_")
    os.close(fd)

    try:
        minio_client.fget_object(bucket, task.file_path, tmp_path)
    except Exception as e:
        _cleanup_temp_file(tmp_path)
        logger.error(f"[PPT] Download from MinIO failed: {e}")
        raise HTTPException(status_code=500, detail="File download failed")

    filename = f"{task.title}.pptx"
    background_tasks.add_task(_cleanup_temp_file, tmp_path)
    return FileResponse(
        path=tmp_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
