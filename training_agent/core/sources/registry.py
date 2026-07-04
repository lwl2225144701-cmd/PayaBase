"""Registry for document sources."""

from core.sources.base import DocumentSource
from core.sources.feishu import FeishuDocumentSource
from core.sources.google_drive import GoogleDriveSource

_SOURCE_REGISTRY: dict[str, type[DocumentSource]] = {
    "feishu": FeishuDocumentSource,
    "google_drive": GoogleDriveSource,
}


def get_source(source_type: str) -> DocumentSource:
    """Get a DocumentSource instance by type name.

    Args:
        source_type: One of "feishu", "google_drive".

    Returns:
        Instantiated DocumentSource.

    Raises:
        ValueError: If source_type is unknown.
    """
    cls = _SOURCE_REGISTRY.get(source_type)
    if not cls:
        available = ", ".join(_SOURCE_REGISTRY.keys())
        raise ValueError(f"Unknown source type: {source_type}. Available: {available}")
    return cls()
