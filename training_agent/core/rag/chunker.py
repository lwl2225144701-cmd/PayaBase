"""Text Chunker.

Chunk documents by paragraph/heading.
"""

from typing import Optional

from langchain_text_splitters import (
    MarkdownTextSplitter,
    RecursiveCharacterTextSplitter,
)
from langchain_core.documents import Document


def _source_display_name(metadata: dict) -> str:
    source_type = metadata.get("source_type") or "local"
    title = (
        metadata.get("title")
        or metadata.get("document_title")
        or metadata.get("filename")
        or metadata.get("source_file")
        or "未知文档"
    )
    title = str(title).rsplit("/", 1)[-1]

    if source_type == "feishu":
        return f"飞书文档-{title}"
    if source_type == "google_drive":
        return f"Google Drive-{title}"
    return f"知识库-{title}"


def _apply_source_metadata(chunks: list[Document]) -> list[Document]:
    for chunk in chunks:
        metadata = dict(chunk.metadata or {})
        metadata["source_type"] = metadata.get("source_type") or "local"
        metadata["source"] = _source_display_name(metadata)
        chunk.metadata = metadata
    return chunks


def _with_source_type(documents: list[Document], source_type: str | None) -> list[Document]:
    if not source_type:
        return documents
    for doc in documents:
        metadata = dict(doc.metadata or {})
        metadata["source_type"] = source_type
        doc.metadata = metadata
    return documents


class TextChunker:
    """Text chunker by paragraph/heading."""

    def __init__(
        self,
        chunk_size: int = 500,
        chunk_overlap: int = 50,
        length_function: Optional[callable] = None,
    ):
        """Initialize chunker.

        Args:
            chunk_size: Maximum chunk size in characters
            chunk_overlap: Overlap between chunks
            length_function: Function to calculate text length
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.length_function = length_function or len

    def _get_splitter(self, file_type: str) -> RecursiveCharacterTextSplitter:
        """Get splitter by file type.

        Args:
            file_type: File type (pdf, md, txt, etc.)

        Returns:
            Text splitter instance
        """
        if file_type == "pdf":
            separators = ["\n\n", "\n", "。", ". ", " ", ""]
        elif file_type == "md":
            separators = ["\n# ", "\n## ", "\n### ", "\n#### ", "\n```", "\n\n", "\n", "。", ". ", " ", ""]
        elif file_type in ("doc", "docx"):
            separators = ["\n\n", "\n[表格", "\n", "。", ". ", " ", ""]
        else:
            separators = ["\n\n", "\n", "。", ". ", " ", ""]

        return RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=separators,
            length_function=self.length_function,
        )

    def _get_markdown_splitter(self) -> MarkdownTextSplitter:
        """Get Markdown-aware splitter.

        Returns:
            Markdown text splitter
        """
        return MarkdownTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

    def chunk_documents(
        self,
        documents: list[Document],
        file_type: str = "auto",
        source_type: str | None = None,
    ) -> list[Document]:
        """Chunk documents.

        Args:
            documents: List of LangChain Documents
            file_type: File type hint (auto, pdf, md, txt)
            source_type: Optional source type override (local, feishu, google_drive)

        Returns:
            List of chunked Documents
        """
        if not documents:
            return []

        documents = _with_source_type(documents, source_type)

        if file_type == "auto":
            first_source = documents[0].metadata.get("source_file", "")
            if first_source:
                file_type = first_source.split(".")[-1].lower()
            else:
                file_type = "txt"

        if file_type == "md":
            splitter = self._get_markdown_splitter()
        else:
            splitter = self._get_splitter(file_type)

        return _apply_source_metadata(splitter.split_documents(documents))

    def chunk_text(
        self,
        text: str,
        metadata: Optional[dict] = None,
    ) -> list[Document]:
        """Chunk plain text.

        Args:
            text: Plain text content
            metadata: Optional metadata dict

        Returns:
            List of chunked Documents
        """
        doc = Document(page_content=text, metadata=metadata or {})
        return self.chunk_documents([doc])

    def chunk_by_tokens(
        self,
        documents: list[Document],
        tokens_per_chunk: int = 256,
    ) -> list[Document]:
        """Chunk by estimated token count.

        Args:
            documents: List of LangChain Documents
            tokens_per_chunk: Approximate tokens per chunk

        Returns:
            List of chunked Documents
        """
        chunk_size = tokens_per_chunk * 4
        original_size = self.chunk_size
        self.chunk_size = chunk_size

        chunks = self.chunk_documents(documents)

        self.chunk_size = original_size
        return chunks
