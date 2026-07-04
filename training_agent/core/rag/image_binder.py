import io
import logging
import re
import uuid
from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session
from minio import Minio

from core.config import settings

logger = logging.getLogger(__name__)


class ImageBinder:
    """图片关联处理器 - 将chunk与图片绑定"""

    def __init__(self):
        self.engine = create_engine(settings.sync_database_url)
        self.minio_client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )

    def bind_images_to_chunks(
        self,
        doc_id: str,
        tenant_id: str,
        chunks_data: list[dict],
    ):
        """为每个chunk绑定其包含的图片

        Args:
            doc_id: 文档ID
            tenant_id: 租户ID
            chunks_data: 分块后的数据列表，每个包含 content 和 chunk_id
        """
        for chunk_data in chunks_data:
            content = chunk_data.get("content", "")
            chunk_id = chunk_data.get("chunk_id")

            if not chunk_id:
                continue

            image_ids = self._extract_image_ids(content)

            if not image_ids:
                continue

            for image_id in image_ids:
                upload_file = self._get_upload_file(image_id, tenant_id)
                if not upload_file:
                    continue

                self._create_binding(
                    tenant_id=tenant_id,
                    document_id=doc_id,
                    segment_id=chunk_id,
                    attachment_id=upload_file["id"],
                )

    def _extract_image_ids(self, text: str) -> list[str]:
        """从文本提取图片ID"""
        pattern = r"!\[[^\]]*\]\(/files/([^/]+)/file-preview\)"
        matches = re.findall(pattern, text)
        return matches

    def upload_image_and_get_markdown(
        self,
        tenant_id: str,
        image_bytes: bytes,
        extension: str = "png",
        name_prefix: str = "image",
    ) -> tuple[str, str]:
        """上传图片到MinIO和upload_files，返回(upload_file_id, markdown_link)。"""
        ext = extension.lower().lstrip(".") or "png"
        file_id = str(uuid.uuid4())
        key = f"image_files/{tenant_id}/{file_id}.{ext}"
        mime_type = f"image/{'jpeg' if ext == 'jpg' else ext}"

        self.minio_client.put_object(
            settings.minio_bucket,
            key,
            io.BytesIO(image_bytes),
            len(image_bytes),
            content_type=mime_type,
        )

        with Session(self.engine) as db:
            db.execute(
                text("""
                    INSERT INTO upload_files
                    (id, tenant_id, storage_type, key, name, size, extension, mime_type, created_at)
                    VALUES (:id, :tenant_id, :storage_type, :key, :name, :size, :extension, :mime_type, NOW())
                """),
                {
                    "id": file_id,
                    "tenant_id": tenant_id,
                    "storage_type": "minio",
                    "key": key,
                    "name": f"{name_prefix}_{file_id}.{ext}",
                    "size": len(image_bytes),
                    "extension": ext,
                    "mime_type": mime_type,
                },
            )
            db.commit()

        return file_id, f"![image](/files/{file_id}/file-preview)"

    def describe_image_with_vision(self, image_bytes: bytes, extension: str = "png") -> str:
        """调用Vision模型识别图片文本，失败则返回空字符串。"""
        from core.llm.factory import is_vision_enabled

        if not settings.index_enable_image_vision or not is_vision_enabled():
            return ""

        try:
            import base64
            from core.llm.factory import get_llm_client
            from core.prompts.vision import VISION_PROMPT

            mime = f"image/{'jpeg' if extension.lower() == 'jpg' else extension.lower()}"
            image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            return get_llm_client("vision").chat_with_image(image_b64, VISION_PROMPT, mime_type=mime).strip()
        except Exception as e:
            logger.warning(f"[ImageBinder] Vision解析失败: {e}")
            return ""

    def _get_upload_file(self, image_id: str, tenant_id: str) -> Optional[dict]:
        """查询UploadFile"""
        with Session(self.engine) as db:
            result = db.execute(
                text("""
                    SELECT id FROM upload_files
                    WHERE key LIKE :pattern AND tenant_id = :tenant_id
                """),
                {"pattern": f"%{image_id}%", "tenant_id": tenant_id}
            )
            row = result.mappings().first()
            return dict(row) if row else None

    def _create_binding(
        self,
        tenant_id: str,
        document_id: str,
        segment_id: str,
        attachment_id: str,
    ):
        """创建绑定关系"""
        with Session(self.engine) as db:
            binding_id = str(uuid.uuid4())
            db.execute(
                text("""
                    INSERT INTO segment_attachment_bindings
                    (id, tenant_id, document_id, segment_id, attachment_id, created_at)
                    VALUES (:id, :tenant_id, :document_id, :segment_id, :attachment_id, NOW())
                """),
                {
                    "id": binding_id,
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "segment_id": segment_id,
                    "attachment_id": attachment_id,
                }
            )
            db.commit()

    def close(self):
        self.engine.dispose()
