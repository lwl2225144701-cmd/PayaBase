import io
import uuid
from typing import Optional

import pypdfium2
from PIL import Image
from langchain_core.documents import Document
from minio import Minio

from core.config import settings


SUPPORTED_IMAGE_FORMATS = {".jpeg", ".jpg", ".png", ".jp2", ".gif", ".bmp", ".tiff", ".tif"}


class PDFParser:
    """PDF解析器 - 文本 + 图片提取"""

    def __init__(self, minio_client: Optional[Minio] = None):
        self.minio_client = minio_client
        self._uploaded_files = []

    def extract(
        self,
        file_data: bytes,
        kb_id: str,
        doc_id: str,
        tenant_id: str,
    ) -> list[Document]:
        """提取PDF文本和图片

        Args:
            file_data: PDF文件字节
            kb_id: 知识库ID
            doc_id: 文档ID
            tenant_id: 租户ID

        Returns:
            Document列表，每页一个Document
        """
        pdf = pypdfium2.PdfDocument(file_data)
        documents = []
        self._uploaded_files = []

        for page_num in range(len(pdf)):
            page = pdf[page_num]

            text = self._extract_text(page)

            image_urls = self._extract_images(
                page, kb_id, doc_id, tenant_id, page_num
            )

            content = text
            for img_url in image_urls:
                content += f"\n![image]({img_url})\n"

            if content.strip():
                documents.append(
                    Document(
                        page_content=content,
                        metadata={
                            "kb_id": kb_id,
                            "doc_id": doc_id,
                            "tenant_id": tenant_id,
                            "page": page_num + 1,
                        }
                    )
                )

        return documents

    def _extract_text(self, page) -> str:
        """提取页面文本"""
        text_page = page.get_textpage()
        text = text_page.get_text_bounded()
        return text or ""

    def _extract_images(
        self,
        page,
        kb_id: str,
        doc_id: str,
        tenant_id: str,
        page_num: int,
    ) -> list[str]:
        """提取页面图片"""
        image_urls = []

        try:
            pil_images = page.get_pil_image()
        except Exception:
            return image_urls

        if not pil_images:
            return image_urls

        if not isinstance(pil_images, list):
            pil_images = [pil_images]

        for img_index, img in enumerate(pil_images):
            if not img:
                continue

            img_format = img.format
            if not img_format:
                continue

            ext = img_format.lower()
            if ext == "jpeg":
                ext = "jpg"

            if ext not in ["jpg", "jpeg", "png", "jp2", "gif", "bmp", "tiff", "tif"]:
                continue

            img_id = str(uuid.uuid4())

            img_byte_arr = io.BytesIO()
            try:
                img.save(img_byte_arr, format=img_format.upper())
            except Exception:
                continue
            img_bytes = img_byte_arr.getvalue()

            key = f"image_files/{tenant_id}/{img_id}.{ext}"
            self._upload_to_minio(key, img_bytes, f"image/{ext}")

            upload_file_id = self._save_upload_file(
                tenant_id=tenant_id,
                key=key,
                name=f"{img_id}.{ext}",
                size=len(img_bytes),
                extension=ext,
                mime_type=f"image/{ext}",
            )

            image_url = f"/files/{upload_file_id}/file-preview"
            image_urls.append(image_url)

        return image_urls

    def _upload_to_minio(self, key: str, data: bytes, content_type: str):
        """上传到MinIO"""
        if not self.minio_client:
            self.minio_client = Minio(
                settings.minio_endpoint,
                access_key=settings.minio_access_key,
                secret_key=settings.minio_secret_key,
                secure=False,
            )

        self.minio_client.put_object(
            settings.minio_bucket,
            key,
            io.BytesIO(data),
            len(data),
            content_type=content_type,
        )

    def _save_upload_file(
        self,
        tenant_id: str,
        key: str,
        name: str,
        size: int,
        extension: str,
        mime_type: str,
    ) -> str:
        """保存UploadFile记录"""
        from sqlalchemy import create_engine, text
        from sqlalchemy.orm import Session

        engine = create_engine(settings.sync_database_url)
        file_id = str(uuid.uuid4())

        with Session(engine) as db:
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
                    "name": name,
                    "size": size,
                    "extension": extension,
                    "mime_type": mime_type,
                }
            )
            db.commit()

        engine.dispose()

        self._uploaded_files.append(file_id)
        return file_id

    def get_uploaded_files(self) -> list[str]:
        """获取已上传的文件ID列表"""
        return self._uploaded_files