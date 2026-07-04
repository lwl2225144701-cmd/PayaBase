"""Document Parser.

Supports multi-format document parsing (PDF, DOCX, Markdown, TXT).
"""

from typing import Optional
from pathlib import Path
import logging

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class DocumentParser:
    """Multi-format document parser."""

    def __init__(self, encoding: str = "utf-8"):
        """Initialize parser.

        Args:
            encoding: Text encoding for text files
        """
        self.encoding = encoding
        self._loaders = None

    @property
    def SUPPORTED_TYPES(self):
        """Lazy loaders to avoid import errors."""
        from langchain_community.document_loaders import (
            PyPDFLoader,
            UnstructuredWordDocumentLoader,
            TextLoader,
        )
        return {
            "pdf": PyPDFLoader,
            "docx": UnstructuredWordDocumentLoader,
            "doc": UnstructuredWordDocumentLoader,
            "txt": TextLoader,
            "md": TextLoader,
        }

    def parse(self, file_path: str) -> list[Document]:
        """Parse document, return LangChain Document list.

        Args:
            file_path: Path to document file

        Returns:
            List of LangChain Documents

        Raises:
            ValueError: If file type is not supported
        """
        path = Path(file_path)
        ext = path.suffix.lower().lstrip(".")

        if ext not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported file type: {ext}")

        loader_class = self.SUPPORTED_TYPES[ext]

        if ext == "txt" or ext == "md":
            loader = loader_class(file_path, encoding=self.encoding)
        else:
            loader = loader_class(file_path)

        return loader.load()

    def parse_with_metadata(
        self,
        file_path: str,
        kb_id: Optional[str] = None,
        doc_id: Optional[str] = None,
    ) -> list[Document]:
        """Parse document with metadata.

        Args:
            file_path: Path to document file
            kb_id: Knowledge base ID
            doc_id: Document ID

        Returns:
            List of LangChain Documents with metadata
        """
        documents = self.parse(file_path)

        for doc in documents:
            doc.metadata["kb_id"] = kb_id
            doc.metadata["doc_id"] = doc_id
            doc.metadata["source_file"] = str(file_path)

        return documents

    def is_supported(self, file_path: str) -> bool:
        """Check if file type is supported.

        Args:
            file_path: Path to file

        Returns:
            True if supported
        """
        ext = Path(file_path).suffix.lower().lstrip(".")
        return ext in self.SUPPORTED_TYPES