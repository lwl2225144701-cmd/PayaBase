import base64
import io
import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

import pypdfium2
from PIL import Image
from langchain_core.documents import Document
from minio import Minio
from core.infrastructure.minio.client import get_minio_client

from core.config import settings


logger = logging.getLogger(__name__)

# 单页抽取文字少于该字数时，视为扫描版/图片版页面，触发 OCR 兜底
MIN_TEXT_LEN = 50

# OCR 并发数：扫描版 PDF 逐页调 Vision LLM，并发可显著缩短整体耗时
OCR_CONCURRENCY = 4

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

        n_pages = len(pdf)

        # 1. 先并发无关地抽取全文字层（本地操作，快），并标记需要 OCR 的页面
        page_texts: dict[int, str] = {}
        ocr_needed: list[int] = []
        for page_num in range(n_pages):
            page = pdf[page_num]
            text = self._extract_text_layer(page)
            page_texts[page_num] = text
            if len(text.strip()) < MIN_TEXT_LEN:
                ocr_needed.append(page_num)

        # 2. 并发对需 OCR 的页面调用 Vision LLM 转录文字
        ocr_results: dict[int, str] = {}
        if ocr_needed:
            logger.info(
                f"[PDF OCR] 共 {n_pages} 页, {len(ocr_needed)} 页需OCR, "
                f"并发数={OCR_CONCURRENCY}"
            )
            with ThreadPoolExecutor(max_workers=OCR_CONCURRENCY) as executor:
                future_to_page = {
                    executor.submit(self._ocr_page, file_data, pn): pn
                    for pn in ocr_needed
                }
                for future in future_to_page:
                    pn = future_to_page[future]
                    try:
                        ocr_results[pn] = future.result()
                    except Exception as e:
                        logger.warning(f"[PDF OCR] 页面 {pn + 1} 并发任务异常, 回退: {e}")
                        ocr_results[pn] = ""

        # 3. 组装文档：OCR 文本比原文字层更丰富时才替换
        for page_num in range(n_pages):
            raw_text = page_texts[page_num]
            ocr_text = ocr_results.get(page_num, "")
            if ocr_text and len(ocr_text.strip()) > len(raw_text.strip()):
                if page_num in ocr_needed:
                    logger.info(
                        f"[PDF OCR] 页面 {page_num + 1} 文字层仅 {len(raw_text.strip())} 字, "
                        f"已用OCR补充为 {len(ocr_text.strip())} 字"
                    )
                final_text = ocr_text
            else:
                final_text = raw_text

            image_urls = self._extract_images(
                pdf[page_num], kb_id, doc_id, tenant_id, page_num
            )

            content = final_text
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

    def _extract_text_layer(self, page) -> str:
        """仅抽取页面文字层（不触发 OCR）"""
        try:
            text_page = page.get_textpage()
            return text_page.get_text_bounded() or ""
        except Exception as e:
            logger.warning(f"[PDF] 文字层提取失败: {e}")
            return ""

    def _ocr_page(self, file_data, page_num: int) -> str:
        """将指定页渲染为图片, 调用 Vision LLM 转录文字 (扫描版 PDF 兜底)

        每个线程独立打开一份 PdfDocument 渲染并关闭, 避免多线程共享同一文档对象
        (pypdfium2 的 PdfDocument 非线程安全, 并发渲染会导致渲染异常与内存暴涨)。
        file_data 为不可变字节, 多线程序列化安全。
        """
        try:
            from core.llm.factory import get_llm_client, is_vision_enabled
            if not is_vision_enabled():
                return ""
            from core.prompts.vision import OCR_PROMPT

            pdf = pypdfium2.PdfDocument(file_data)
            try:
                page = pdf[page_num]
                pil_image = page.render(scale=2.0).to_pil()
            finally:
                pdf.close()
            buf = io.BytesIO()
            pil_image.save(buf, format="PNG")
            img_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

            result = get_llm_client("vision").chat_with_image(
                img_b64, OCR_PROMPT, mime_type="image/png"
            )
            return (result or "").strip()
        except Exception as e:
            logger.warning(f"[PDF OCR] 页面 {page_num + 1} 识别失败, 回退原文字: {e}")
            return ""

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
            self.minio_client = get_minio_client()

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