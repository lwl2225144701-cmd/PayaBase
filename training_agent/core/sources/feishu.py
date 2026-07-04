"""Feishu/Lark document source.

Preferred path for docx/wiki documents:
1) Parse block content into markdown (including simple table markdown)
2) Extract image blocks, download image bytes
3) Vision OCR/caption injection
4) Upload images to MinIO and inject preview markdown links

Fallback path:
- Export to .docx via Feishu drive export API
"""

import logging
import re
import time
from typing import Any, Optional

import httpx

from core.config import settings
from core.rag.image_binder import ImageBinder
from core.sources.base import DocumentSource, DocumentSourceResult
from core.sources.exceptions import SourceAuthError, SourceFetchError

logger = logging.getLogger(__name__)

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
FEISHU_DOC_BLOCKS_URL = f"{FEISHU_API_BASE}/docx/v1/documents/{{doc_token}}/blocks"
FEISHU_DOC_CHILDREN_URL = f"{FEISHU_API_BASE}/docx/v1/documents/{{doc_token}}/blocks/{{block_id}}/children"
FEISHU_DOC_IMAGE_URL = f"{FEISHU_API_BASE}/drive/v1/medias/{{file_token}}/download"

# URL patterns: https://xxx.feishu.cn/docx/TOKEN, /wiki/TOKEN, /sheets/TOKEN
FEISHU_URL_PATTERN = re.compile(r"https?://[^/]+/(?:docx|wiki|sheets|bitable)/([a-zA-Z0-9]+)")


class FeishuDocumentSource(DocumentSource):
    """Fetches documents from Feishu/Lark."""

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
    ):
        self.app_id = app_id or settings.feishu_app_id
        self.app_secret = app_secret or settings.feishu_app_secret
        self._tenant_token: Optional[str] = None
        self._token_expires_at: float = 0

    async def _get_tenant_access_token(self) -> str:
        """Obtain or refresh tenant_access_token using app credentials."""
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=10.0,
            )
            if resp.status_code != 200:
                raise SourceAuthError(f"Feishu auth failed: HTTP {resp.status_code}")
            data = resp.json()
            if data.get("code") != 0:
                raise SourceAuthError(f"Feishu auth error: {data.get('msg')}")
            self._tenant_token = data["tenant_access_token"]
            self._token_expires_at = time.time() + data.get("expire", 7200) - 300
            return self._tenant_token

    async def _get_token(self) -> str:
        if self._tenant_token and time.time() < self._token_expires_at:
            return self._tenant_token
        return await self._get_tenant_access_token()

    def _extract_doc_info(self, url_or_id: str) -> tuple[str, str]:
        """Extract (document_token, doc_type) from a Feishu URL or raw token."""
        if url_or_id.startswith("http"):
            match = FEISHU_URL_PATTERN.search(url_or_id)
            if not match:
                raise SourceFetchError(f"Cannot parse Feishu URL: {url_or_id}")
            token = match.group(1)
            if "/docx/" in url_or_id:
                return token, "docx"
            if "/wiki/" in url_or_id:
                return token, "wiki"
            if "/sheets/" in url_or_id:
                return token, "sheets"
            return token, "docx"
        return url_or_id, "docx"

    async def _resolve_wiki_token(self, wiki_token: str, headers: dict[str, str]) -> tuple[str, str]:
        """Resolve a wiki node token to its underlying document token and type."""
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{FEISHU_API_BASE}/wiki/v2/spaces/get_node",
                params={"token": wiki_token},
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code != 200:
                raise SourceFetchError(f"Failed to resolve wiki token: HTTP {resp.status_code}")
            data = resp.json()
            if data.get("code") != 0:
                raise SourceFetchError(f"Feishu wiki API error: {data.get('msg')}")
            node = data.get("data", {}).get("node", {})
            obj_token = node.get("obj_token", wiki_token)
            obj_type = node.get("obj_type", "docx")
            return obj_token, obj_type

    async def _fetch_doc_blocks(self, doc_token: str, headers: dict[str, str]) -> dict[str, dict[str, Any]]:
        """Fetch root and child blocks from Feishu docx API."""
        block_map: dict[str, dict[str, Any]] = {}
        async with httpx.AsyncClient() as client:
            root_resp = await client.get(
                FEISHU_DOC_BLOCKS_URL.format(doc_token=doc_token),
                headers=headers,
                timeout=15.0,
            )
            if root_resp.status_code != 200:
                raise SourceFetchError(f"Feishu blocks API failed: HTTP {root_resp.status_code}")
            root_data = root_resp.json()
            if root_data.get("code") != 0:
                raise SourceFetchError(f"Feishu blocks API error: {root_data.get('msg')}")

            root_items = root_data.get("data", {}).get("items", []) or []
            for item in root_items:
                bid = item.get("block_id")
                if bid:
                    block_map[bid] = item

            queue = [b.get("block_id") for b in root_items if b.get("has_children")]
            visited: set[str] = set()
            while queue:
                block_id = queue.pop(0)
                if not block_id or block_id in visited:
                    continue
                visited.add(block_id)

                child_resp = await client.get(
                    FEISHU_DOC_CHILDREN_URL.format(doc_token=doc_token, block_id=block_id),
                    headers=headers,
                    timeout=15.0,
                )
                if child_resp.status_code != 200:
                    continue
                child_data = child_resp.json()
                if child_data.get("code") != 0:
                    continue
                child_items = child_data.get("data", {}).get("items", []) or []
                for item in child_items:
                    child_id = item.get("block_id")
                    if child_id and child_id not in block_map:
                        block_map[child_id] = item
                    if item.get("has_children"):
                        queue.append(child_id)

        return block_map

    def _extract_text_from_elements(self, elements: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for element in elements or []:
            txt = (
                element.get("text_run", {}).get("content")
                or element.get("mention_user", {}).get("text")
                or element.get("mention_doc", {}).get("text")
                or element.get("equation", {}).get("content")
                or ""
            )
            if txt:
                parts.append(txt)
        return "".join(parts).strip()

    def _table_to_markdown(self, table: dict[str, Any]) -> str:
        """Render table to markdown; degrade gracefully for merged/nested tables."""
        rows = table.get("rows") or []
        if rows and isinstance(rows[0], list):
            md_rows: list[str] = []
            max_cols = max((len(r) for r in rows if isinstance(r, list)), default=0)
            if max_cols == 0:
                return ""
            for ridx, row in enumerate(rows):
                normalized = [str(c).strip() if c is not None else "" for c in row[:max_cols]]
                if len(normalized) < max_cols:
                    normalized.extend([""] * (max_cols - len(normalized)))
                md_rows.append("| " + " | ".join(normalized) + " |")
                if ridx == 0:
                    md_rows.append("| " + " | ".join(["---"] * max_cols) + " |")
            return "\n".join(md_rows)

        cells = table.get("cells") or table.get("table_cells") or []
        if not isinstance(cells, list) or not cells:
            return ""

        def _cell_text(cell: dict[str, Any]) -> str:
            value = (
                cell.get("text")
                or cell.get("content")
                or cell.get("display")
                or cell.get("value")
                or ""
            )
            if isinstance(value, list):
                pieces: list[str] = []
                for v in value:
                    if isinstance(v, dict):
                        t = (
                            v.get("text")
                            or v.get("content")
                            or v.get("value")
                            or ""
                        )
                        if t:
                            pieces.append(str(t).strip())
                    else:
                        t = str(v).strip()
                        if t:
                            pieces.append(t)
                return " ".join(pieces)
            if isinstance(value, dict):
                return str(value.get("text") or value.get("content") or value.get("value") or "").strip()
            return str(value).strip()

        def _to_int(v: Any, default: int) -> int:
            try:
                return int(v)
            except Exception:
                return default

        # Detect coordinates and merge spans; for complex shape, emit a stable semantic fallback.
        lines: list[str] = ["[复杂表格展开]"]
        for idx, cell in enumerate(cells, 1):
            if not isinstance(cell, dict):
                continue
            row = _to_int(cell.get("row_index", cell.get("row", idx - 1)), idx - 1)
            col = _to_int(cell.get("col_index", cell.get("col", 0)), 0)
            row_span = _to_int(cell.get("row_span", 1), 1)
            col_span = _to_int(cell.get("col_span", 1), 1)
            text_value = _cell_text(cell)
            if not text_value:
                continue
            span_suffix = ""
            if row_span > 1 or col_span > 1:
                span_suffix = f" (合并 {row_span}x{col_span})"
            lines.append(f"- R{row + 1}C{col + 1}{span_suffix}: {text_value}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _block_to_markdown_line(self, block: dict[str, Any]) -> str:
        btype = block.get("block_type")
        if btype in (3, 4, 5, 6, 7, 8):
            heading = (
                block.get("heading1")
                or block.get("heading2")
                or block.get("heading3")
                or block.get("heading4")
                or block.get("heading5")
                or block.get("heading6")
                or {}
            )
            return self._extract_text_from_elements(heading.get("elements", []))
        if btype == 2:
            return self._extract_text_from_elements((block.get("text") or {}).get("elements", []))
        if btype == 12:
            text_value = self._extract_text_from_elements((block.get("bullet") or {}).get("elements", []))
            return f"- {text_value}" if text_value else ""
        if btype == 13:
            text_value = self._extract_text_from_elements((block.get("ordered") or {}).get("elements", []))
            return f"1. {text_value}" if text_value else ""
        if btype == 14:
            text_value = self._extract_text_from_elements((block.get("code") or {}).get("elements", []))
            return f"```text\n{text_value}\n```" if text_value else ""
        if btype == 19:
            text_value = self._extract_text_from_elements((block.get("quote") or {}).get("elements", []))
            return f"> {text_value}" if text_value else ""
        if btype == 31:
            return self._table_to_markdown(block.get("table") or {})
        return ""

    async def _download_image_bytes(self, image_token: str, headers: dict[str, str]) -> bytes:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                FEISHU_DOC_IMAGE_URL.format(file_token=image_token),
                headers=headers,
                timeout=30.0,
            )
            if resp.status_code != 200:
                raise SourceFetchError(f"Feishu image download failed: HTTP {resp.status_code}")
            return resp.read()

    async def _fetch_docx_markdown_with_assets(
        self,
        doc_token: str,
        headers: dict[str, str],
        tenant_id: str | None,
    ) -> str:
        blocks = await self._fetch_doc_blocks(doc_token, headers)
        if not blocks:
            return ""

        lines: list[str] = []
        binder = ImageBinder() if tenant_id else None
        try:
            for block in blocks.values():
                line = self._block_to_markdown_line(block)
                if line:
                    lines.append(line)

                if block.get("block_type") != 27:
                    continue

                image_info = block.get("image") or {}
                image_token = image_info.get("token") or image_info.get("file_token")
                if not image_token:
                    continue

                try:
                    image_bytes = await self._download_image_bytes(image_token, headers)
                except Exception as exc:
                    logger.warning(f"Feishu image download failed, token={image_token}: {exc}")
                    continue

                markdown_link = ""
                vision_text = ""
                if binder:
                    try:
                        _, markdown_link = binder.upload_image_and_get_markdown(
                            tenant_id=tenant_id,
                            image_bytes=image_bytes,
                            extension="png",
                            name_prefix="feishu",
                        )
                    except Exception as exc:
                        logger.warning(f"Feishu image upload failed: {exc}")
                    vision_text = binder.describe_image_with_vision(image_bytes, extension="png")

                if markdown_link:
                    lines.append(markdown_link)
                if vision_text:
                    lines.append(f"[图片解析]\n{vision_text}")
        finally:
            if binder:
                binder.close()

        return "\n\n".join([s for s in lines if s]).strip()

    async def _export_to_docx(self, file_token: str, file_type: str, headers: dict[str, str]) -> bytes:
        """Export a Feishu document to docx format and download the result."""
        async with httpx.AsyncClient() as client:
            type_mapping = {"docx": "docx", "wiki": "docx", "sheets": "sheet"}
            export_type = type_mapping.get(file_type, "docx")

            resp = await client.post(
                f"{FEISHU_API_BASE}/drive/v1/export_tasks",
                headers=headers,
                json={"file_token": file_token, "type": export_type},
                timeout=30.0,
            )
            if resp.status_code != 200:
                raise SourceFetchError(f"Feishu export task creation failed: HTTP {resp.status_code}")
            data = resp.json()
            if data.get("code") != 0:
                raise SourceFetchError(f"Feishu export API error: {data.get('msg')}")

            ticket = data.get("data", {}).get("ticket")
            if not ticket:
                raise SourceFetchError("Feishu export: no ticket returned")

            file_token_result = ""
            for _ in range(30):
                await _async_sleep(2)
                poll_resp = await client.get(
                    f"{FEISHU_API_BASE}/drive/v1/export_tasks/{ticket}",
                    headers=headers,
                    params={"file_token": file_token},
                    timeout=10.0,
                )
                if poll_resp.status_code != 200:
                    continue
                poll_data = poll_resp.json()
                status = poll_data.get("data", {}).get("status")
                if status == 0:
                    file_token_result = poll_data.get("data", {}).get("file_token") or ""
                    break
                if status == 1:
                    continue
                raise SourceFetchError(f"Feishu export failed with status: {status}")

            if not file_token_result:
                raise SourceFetchError("Feishu export timed out after 60s")

            download_resp = await client.get(
                f"{FEISHU_API_BASE}/drive/v1/export_tasks/{ticket}/download",
                headers=headers,
                params={"file_token": file_token_result},
                timeout=60.0,
            )
            if download_resp.status_code != 200:
                raise SourceFetchError(f"Feishu export download failed: HTTP {download_resp.status_code}")
            return download_resp.read()

    async def fetch(self, url_or_id: str, **kwargs) -> DocumentSourceResult:
        """Fetch a Feishu document.

        For docx/wiki:
        - Try block-level markdown extraction with image enrichment first.
        - Fall back to docx export on any failure.
        """
        token = kwargs.get("access_token") or await self._get_token()
        tenant_id = kwargs.get("tenant_id")
        doc_token, doc_type = self._extract_doc_info(url_or_id)
        headers = {"Authorization": f"Bearer {token}"}

        if doc_type == "wiki":
            doc_token, resolved_type = await self._resolve_wiki_token(doc_token, headers)
        else:
            resolved_type = doc_type

        if resolved_type == "docx":
            try:
                markdown = await self._fetch_docx_markdown_with_assets(doc_token, headers, tenant_id)
                if markdown:
                    filename = kwargs.get("title", f"feishu_{doc_token}.md")
                    if not filename.endswith(".md"):
                        filename += ".md"
                    return DocumentSourceResult(
                        content=markdown.encode("utf-8"),
                        filename=filename,
                        file_type="md",
                        source_type="feishu",
                        source_url=url_or_id,
                    )
            except Exception as exc:
                logger.warning(f"Feishu block parse failed, fallback to export docx: {exc}")

        content_bytes = await self._export_to_docx(doc_token, resolved_type, headers)
        filename = kwargs.get("title", f"feishu_{doc_token}.docx")
        if not filename.endswith(".docx"):
            filename += ".docx"

        return DocumentSourceResult(
            content=content_bytes,
            filename=filename,
            file_type="docx",
            source_type="feishu",
            source_url=url_or_id,
        )


async def _async_sleep(seconds: float):
    import asyncio
    await asyncio.sleep(seconds)
