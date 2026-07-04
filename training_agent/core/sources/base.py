"""Abstract base for external document sources."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class DocumentSourceResult:
    """Unified return type from any DocumentSource.fetch()."""

    content: bytes       # raw file bytes (ready for MinIO upload)
    filename: str        # display name, e.g. "Q3 Report.md"
    file_type: str       # extension without dot: "md", "pdf", "docx", etc.
    source_type: str     # "feishu", "google_drive"
    source_url: str      # original URL for provenance tracking
    content_length: int  # len(content), computed in __post_init__

    def __post_init__(self):
        self.content_length = len(self.content)


class DocumentSource(ABC):
    """Abstract base class for external document sources."""

    @abstractmethod
    async def fetch(self, url_or_id: str, **kwargs) -> DocumentSourceResult:
        """Fetch a document from the external source.

        Args:
            url_or_id: URL or document identifier specific to the source.
            **kwargs: Source-specific parameters (e.g., title override).

        Returns:
            DocumentSourceResult with raw bytes ready for the indexing pipeline.

        Raises:
            SourceFetchError: If fetching fails.
        """
        ...
