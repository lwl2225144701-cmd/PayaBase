"""Google Drive public link document source.

Downloads publicly shared files from Google Drive using the direct download URL.
Only supports files shared with "Anyone with the link".
"""

import logging
import re
from urllib.parse import unquote

import httpx

from core.sources.base import DocumentSource, DocumentSourceResult
from core.sources.exceptions import SourceFetchError

logger = logging.getLogger(__name__)

# Google Drive URL patterns
GDRIVE_FILE_PATTERN = re.compile(
    r"https?://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
)
GDRIVE_OPEN_PATTERN = re.compile(
    r"https?://drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)"
)

GDRIVE_DOWNLOAD_URL = "https://drive.google.com/uc?export=download"


class GoogleDriveSource(DocumentSource):
    """Fetches publicly shared files from Google Drive."""

    def _extract_file_id(self, url: str) -> str:
        """Extract file ID from various Google Drive URL formats."""
        match = GDRIVE_FILE_PATTERN.search(url)
        if match:
            return match.group(1)
        match = GDRIVE_OPEN_PATTERN.search(url)
        if match:
            return match.group(1)
        raise SourceFetchError(f"Cannot parse Google Drive URL: {url}")

    async def fetch(self, url_or_id: str, **kwargs) -> DocumentSourceResult:
        """Download a publicly shared Google Drive file.

        Args:
            url_or_id: Google Drive share URL.
            **kwargs: Optional overrides:
                - filename (str): Override detected filename.
                - file_type (str): Override detected extension.
        """
        file_id = self._extract_file_id(url_or_id)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                GDRIVE_DOWNLOAD_URL,
                params={"id": file_id},
                timeout=60.0,
            )

            if resp.status_code != 200:
                raise SourceFetchError(
                    f"Google Drive download failed: HTTP {resp.status_code}"
                )

            # Large files trigger a virus scan warning page (HTML response)
            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                confirm_token = self._extract_confirm_token(resp.text)
                if confirm_token:
                    resp = await client.get(
                        GDRIVE_DOWNLOAD_URL,
                        params={"id": file_id, "confirm": confirm_token},
                        timeout=120.0,
                    )
                    if resp.status_code != 200:
                        raise SourceFetchError("Google Drive confirmation download failed")
                else:
                    raise SourceFetchError(
                        "Google Drive returned HTML (file may not be publicly shared)"
                    )

            content = resp.read()

            filename = kwargs.get("filename") or self._extract_filename(
                resp.headers.get("content-disposition", ""), file_id
            )
            file_type = kwargs.get("file_type") or (
                filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
            )

            return DocumentSourceResult(
                content=content,
                filename=filename,
                file_type=file_type,
                source_type="google_drive",
                source_url=url_or_id,
            )

    async def preview(self, url_or_id: str) -> dict[str, object]:
        """Inspect a Google Drive link without persisting it."""
        file_id = self._extract_file_id(url_or_id)

        async with httpx.AsyncClient(follow_redirects=True) as client:
            resp = await client.get(
                GDRIVE_DOWNLOAD_URL,
                params={"id": file_id},
                timeout=30.0,
            )
            if resp.status_code != 200:
                raise SourceFetchError(
                    f"Google Drive preview failed: HTTP {resp.status_code}"
                )

            content_type = resp.headers.get("content-type", "")
            if "text/html" in content_type:
                confirm_token = self._extract_confirm_token(resp.text)
                if confirm_token:
                    resp = await client.get(
                        GDRIVE_DOWNLOAD_URL,
                        params={"id": file_id, "confirm": confirm_token},
                        timeout=30.0,
                    )
                    if resp.status_code != 200:
                        raise SourceFetchError("Google Drive preview confirmation failed")
                else:
                    raise SourceFetchError(
                        "Google Drive returned HTML (file may not be publicly shared)"
                    )

            filename = self._extract_filename(resp.headers.get("content-disposition", ""), file_id)
            file_type = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
            file_size = resp.headers.get("content-length")

            return {
                "source_url": url_or_id,
                "file_id": file_id,
                "file_name": filename,
                "file_type": file_type,
                "file_size": int(file_size) if file_size and file_size.isdigit() else len(resp.content),
                "content_type": content_type,
            }

    def _extract_confirm_token(self, html: str) -> str | None:
        """Extract download confirmation token from Google's warning page."""
        match = re.search(r"confirm=([a-zA-Z0-9_-]+)", html)
        if match:
            return match.group(1)
        match = re.search(r'name="confirm"\s+value="([^"]+)"', html)
        return match.group(1) if match else None

    def _extract_filename(self, content_disposition: str, file_id: str) -> str:
        """Extract filename from Content-Disposition header."""
        if "filename=" in content_disposition:
            match = re.search(r"filename\*=UTF-8''(.+?)(?:;|$)", content_disposition)
            if match:
                return unquote(match.group(1))
            match = re.search(r'filename="([^"]+)"', content_disposition)
            if match:
                return match.group(1)
            match = re.search(r"filename=([^;\s]+)", content_disposition)
            if match:
                return match.group(1)
        return f"gdrive_{file_id}"
