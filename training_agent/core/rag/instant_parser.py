"""Instant File Parser.

Synchronous file parsing for chat attachments.
Supports PDF, DOCX, TXT, MD, and images (via LLM Vision).
"""

import io
import base64
import logging
from pathlib import Path

from core.exceptions import ValidationException
from core.config import settings
from core.prompts.vision import VISION_PROMPT

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {"pdf", "docx", "doc", "txt", "md", "png", "jpg", "jpeg", "gif", "webp", "bmp"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "bmp"}


class InstantFileParser:
    """Synchronous parser for chat attachment files."""

    def parse(self, filename: str, content: bytes) -> str:
        """Parse file content based on extension.

        Args:
            filename: Original filename with extension
            content: Raw file bytes

        Returns:
            Extracted text content

        Raises:
            ValidationException: If file type is not supported
        """
        ext = Path(filename).suffix.lower().lstrip(".")
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValidationException(
                f"不支持的文件格式: .{ext}，支持: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )

        if ext in IMAGE_EXTENSIONS:
            return self._parse_image(content, ext)
        elif ext == "pdf":
            return self._parse_pdf(content)
        elif ext in ("docx", "doc"):
            return self._parse_docx(content)
        else:
            return self._parse_text(content)

    def _parse_pdf(self, content: bytes) -> str:
        """Extract text and images from PDF."""
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(content))
        pages_text: list[str] = []
        image_descriptions: list[str] = []

        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text and text.strip():
                pages_text.append(f"[第{i + 1}页]\n{text.strip()}")

            # Extract images from PDF pages
            if hasattr(page, "images") and page.images:
                for img_idx, img in enumerate(page.images):
                    try:
                        img_data = img.data
                        if img_data and len(img_data) > 100:  # skip tiny icons
                            ext = Path(img.name).suffix.lower().lstrip(".") if img.name else "png"
                            if ext in IMAGE_EXTENSIONS:
                                desc = self._parse_image_safe(img_data, ext, i + 1, img_idx + 1)
                                if desc:
                                    image_descriptions.append(desc)
                    except Exception as e:
                        logger.warning(f"[InstantParser] PDF image extraction failed (page {i+1}, img {img_idx}): {e}")

        parts = []
        if pages_text:
            parts.append("\n\n".join(pages_text))
        if image_descriptions:
            parts.append("\n\n[文档内嵌图片分析]\n" + "\n\n".join(image_descriptions))

        return "\n\n".join(parts) if parts else ""

    def _parse_docx(self, content: bytes) -> str:
        """Extract text from DOCX using python-docx."""
        from docx import Document as DocxDocument

        doc = DocxDocument(io.BytesIO(content))
        paragraphs: list[str] = []
        for para in doc.paragraphs:
            text = para.text.strip()
            if text:
                paragraphs.append(text)
        return "\n".join(paragraphs)

    def _parse_text(self, content: bytes) -> str:
        """Read plain text / markdown content."""
        return content.decode("utf-8", errors="replace")

    def _parse_image(self, content: bytes, ext: str) -> str:
        """Analyze image via LLM Vision.

        Raises:
            ValidationException: If vision is not configured or call fails
        """
        result = self._parse_image_safe(content, ext)
        if result is None:
            raise ValidationException(
                "图片识别不可用：当前未配置 Vision 模型。请设置 LLM_VISION_MODEL 环境变量（如 qwen-vl-plus）。"
            )
        return result

    def _parse_image_safe(self, content: bytes, ext: str, page: int = 0, idx: int = 0) -> str | None:
        """Analyze image via LLM Vision. Returns None if vision is unavailable."""
        from core.llm.client import LLMClient

        b64 = base64.b64encode(content).decode("utf-8")
        mime = f"image/{'jpeg' if ext == 'jpg' else ext}"

        llm = LLMClient()
        try:
            result = llm.chat_with_image(b64, VISION_PROMPT, mime_type=mime)
            if page > 0:
                return f"[第{page}页-图片{idx}]\n{result}"
            return result
        except RuntimeError as e:
            # Vision not configured — graceful skip
            logger.info(f"[InstantParser] Vision unavailable: {e}")
            return None
        except Exception as e:
            logger.error(f"[InstantParser] Vision API failed: {e}")
            if page > 0:
                return f"[第{page}页-图片{idx}] 图片识别失败: {e}"
            return None
