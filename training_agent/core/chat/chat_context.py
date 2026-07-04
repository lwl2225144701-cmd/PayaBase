"""Context building for chat responses."""

import logging

logger = logging.getLogger(__name__)


def build_context_from_chunks(chunks_data: list[dict], limit: int = 5) -> str:
    """Build a readable context string from retrieved chunks."""
    context_parts = []
    for i, chunk in enumerate(chunks_data[:limit], 1):
        content_text = chunk["content"][:700]
        source = chunk.get("source", "未知来源")
        context_parts.append(f"【{i}】[{source}]\n{content_text}")
    return "\n\n".join(context_parts)


def infer_primary_source_label(
    chunks_data: list[dict],
    has_attachments: bool,
) -> str:
    """Infer the primary source label for the response."""
    if has_attachments:
        return "用户上传附件"
    if not chunks_data:
        return "无资料"
    return chunks_data[0].get("source", "知识库文档")


def build_material_text(
    all_attachments: list[tuple[str, str]],
    chunks_data: list[dict],
) -> tuple[str, str]:
    """Assemble material text from attachments and chunks.

    Returns:
        (material_text, source_hint)
    """
    material_parts = []
    if all_attachments:
        for fname, fcontent in all_attachments:
            material_parts.append(f"[用户上传附件:{fname}]\n{fcontent[:4000]}")
    if chunks_data:
        material_parts.append(build_context_from_chunks(chunks_data))
    material_text = "\n\n".join(material_parts)
    source_hint = infer_primary_source_label(chunks_data, bool(all_attachments))
    return material_text, source_hint
