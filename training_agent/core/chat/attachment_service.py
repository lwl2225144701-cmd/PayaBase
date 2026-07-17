"""Attachment validation, parsing, and MinIO upload logic."""

import asyncio
import io
import logging
from pathlib import Path

from core.infrastructure.minio.client import get_minio_client as _get_minio_client

from core.config import settings
from core.exceptions import ValidationException
from core.rag.instant_parser import InstantFileParser

logger = logging.getLogger(__name__)

ALLOWED_ATTACHMENT_TYPES = {"pdf", "docx", "doc", "txt", "md", "png", "jpg", "jpeg", "gif", "webp", "bmp"}


def _put_attachment_object(
    tenant_id: str,
    conversation_id: str,
    filename: str,
    content: bytes,
) -> str:
    """Synchronous MinIO upload."""
    minio_client = _get_minio_client()
    if not minio_client.bucket_exists(settings.minio_bucket):
        minio_client.make_bucket(settings.minio_bucket)

    safe_name = Path(filename).name
    key = f"{settings.temp_attachment_prefix}/{tenant_id}/{conversation_id}/{safe_name}"
    minio_client.put_object(
        settings.minio_bucket,
        key,
        data=io.BytesIO(content),
        length=len(content),
        content_type="application/octet-stream",
    )
    return key


async def save_attachment_to_minio(
    tenant_id: str,
    conversation_id: str,
    filename: str,
    content: bytes,
) -> str:
    """Upload attachment to MinIO temp path asynchronously."""
    key = await asyncio.to_thread(
        _put_attachment_object,
        tenant_id,
        conversation_id,
        filename,
        content,
    )
    logger.info(f"[Chat] Attachment saved to MinIO: {key}")
    return key


async def parse_attachments(
    files: list,
    attachment_parse_semaphore: asyncio.Semaphore,
    tenant_id: str,
    conversation_id: str,
) -> list[tuple[str, str]]:
    """Validate, parse, and upload attachments.

    Returns:
        List of (filename, parsed_text) tuples.
    """
    valid_files = [f for f in files if f.filename]
    all_attachments: list[tuple[str, str]] = []
    parser = InstantFileParser()

    for file in valid_files:
        ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
        if ext not in ALLOWED_ATTACHMENT_TYPES:
            raise ValidationException(
                f"不支持的文件格式: .{ext}，支持: {', '.join(sorted(ALLOWED_ATTACHMENT_TYPES))}"
            )

        content = await file.read()
        if len(content) > settings.max_attachment_size:
            raise ValidationException(
                f"文件过大: {file.filename} ({len(content)} 字节)，最大允许 {settings.max_attachment_size} 字节"
            )

        # Parse file content synchronously
        try:
            async with attachment_parse_semaphore:
                parsed = await asyncio.to_thread(parser.parse, file.filename, content)
            all_attachments.append((file.filename, parsed))
            logger.info(f"[Chat] 附件解析完成, filename={file.filename}, text_len={len(parsed)}")
        except ValidationException:
            raise
        except Exception as e:
            logger.error(f"[Chat] 附件解析失败: {e}", exc_info=True)
            raise ValidationException(f"附件解析失败 ({file.filename}): {e}")

        # Upload original file to MinIO
        try:
            await save_attachment_to_minio(tenant_id, conversation_id, file.filename, content)
        except Exception as e:
            logger.warning(f"[Chat] 附件上传MinIO失败(非致命): {e}")

    return all_attachments
