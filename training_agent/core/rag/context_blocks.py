"""Phase 4 父上下文块生成与上下文扩展。

父上下文块(chunk_context_blocks)仅在索引期生成, 用于检索后补充上下文;
不进入向量、BM25、RRF、Rerank。
"""

import hashlib
import logging
import uuid

from core.config import settings

logger = logging.getLogger(__name__)


def _is_heading_boundary(content: str, meta: dict) -> bool:
    """判断当前 chunk 是否应作为父块的分界起点。

    规则(确定性、保守):
    1. meta 中显式标注了 heading/section_break;
    2. Markdown 一级/二级标题行开头。
    """
    if meta.get("is_heading") or meta.get("section_break"):
        return True
    first_line = (content or "").strip().split("\n")[0].strip()
    if first_line.startswith("# ") or first_line.startswith("## "):
        return True
    return False


def _remove_exact_overlap(left: str, right: str) -> str:
    """确定性前后缀重叠删除: 若 right 前缀与 left 后缀完全相等, 只保留一次。

    不做模糊去重, 避免误删正文。
    """
    max_overlap = min(len(left), len(right), settings.index_chunk_overlap * 3)
    if max_overlap <= 0:
        return right
    for n in range(max_overlap, 0, -1):
        if left[-n:] == right[:n]:
            return right[n:]
    return right


def _estimate_tokens(text: str) -> int:
    """沿用项目既有口径: 1 token ≈ 3 字符。"""
    return max(1, len(text) // 3)


def build_context_blocks_for_document(
    document_id: str,
    chunks_data: list[dict],
) -> tuple[list[dict], list[dict]]:
    """为单个文档的子块分配 sequence_no 并生成父上下文块。

    Args:
        document_id: 文档 ID 字符串。
        chunks_data: 按切片顺序排列的 chunk dict 列表; 会被原地写入
            sequence_no / context_block_id。

    Returns:
        (updated_chunks_data, context_blocks_data)
        - updated_chunks_data: 每个 chunk dict 已写入 sequence_no 和 context_block_id。
        - context_blocks_data: 父上下文块 dict 列表, 可直接入库。
    """
    target_tokens = settings.context_parent_target_tokens
    max_tokens = settings.context_parent_max_tokens
    min_children = settings.context_parent_min_children
    max_children = settings.context_parent_max_children

    # 1) 分配 sequence_no
    for seq, chunk in enumerate(chunks_data):
        chunk["sequence_no"] = seq
        chunk["context_block_id"] = None

    if not chunks_data:
        return chunks_data, []

    context_blocks: list[dict] = []

    # 2) 按规则分组生成父块
    current_group: list[dict] = []
    current_tokens = 0

    def flush_group(force: bool = False) -> None:
        nonlocal current_group, current_tokens
        if not current_group:
            return
        # 非强制 flush 时, 若块数不足 min_children 且后面可能还有 chunk, 先不拆
        # (force=True 表示文档末尾, 必须 flush; 否则尽量满足 min_children)
        if not force and len(current_group) < min_children:
            return

        start_seq = current_group[0]["sequence_no"]
        end_seq = current_group[-1]["sequence_no"]

        # 拼接内容, 只做确定性前后缀重叠删除
        merged_parts: list[str] = [current_group[0]["content"]]
        for prev, nxt in zip(current_group, current_group[1:], strict=False):
            merged_parts.append(_remove_exact_overlap(prev["content"], nxt["content"]))
        merged_content = "".join(merged_parts)

        block_id = str(uuid.uuid4())
        context_version = settings.context_version
        content_hash = hashlib.sha256(
            f"{context_version}::{merged_content}".encode()
        ).hexdigest()

        block = {
            "id": block_id,
            "document_id": document_id,
            "content": merged_content,
            "start_sequence": start_seq,
            "end_sequence": end_seq,
            "token_count": _estimate_tokens(merged_content),
            "content_hash": content_hash,
            "context_version": context_version,
        }
        context_blocks.append(block)

        for chunk in current_group:
            chunk["context_block_id"] = block_id

        current_group = []
        current_tokens = 0

    for chunk in chunks_data:
        content = chunk["content"]
        chunk_tokens = chunk.get("token_count") or _estimate_tokens(content)

        # 若当前 chunk 是章节边界且当前组已满足最小子块数, 优先分开
        if current_group and _is_heading_boundary(content, chunk.get("meta", {})):
            if len(current_group) >= min_children:
                flush_group(force=True)

        # 若加入当前 chunk 会超出上限(子块数或 token), 先 flush
        would_exceed = (
            len(current_group) >= max_children
            or (current_tokens + chunk_tokens > max_tokens and len(current_group) >= min_children)
        )
        if would_exceed and current_group:
            flush_group(force=True)

        current_group.append(chunk)
        current_tokens += chunk_tokens

        # 达到目标 token 数且满足最小子块数, 可以闭合
        if (
            current_tokens >= target_tokens
            and len(current_group) >= min_children
        ):
            flush_group(force=True)

    # 文档末尾 flush 剩余
    flush_group(force=True)

    return chunks_data, context_blocks


def _hash_context_block(block: dict) -> str:
    """为回填脚本复用: 基于内容和版本计算 hash。"""
    return hashlib.sha256(
        f"{block['context_version']}::{block['content']}".encode()
    ).hexdigest()


def build_context_blocks_for_existing_chunks(
    document_id: str,
    chunks: list[dict],
) -> tuple[list[dict], list[dict]]:
    """历史回填入口: 与 build_context_blocks_for_document 行为一致,
    但接收已有 chunk dict(必须含 content / sequence_no 或能被排序)。"""
    # 按 sequence_no 排序; 缺失时保持输入顺序(调用方应已排序)
    sorted_chunks = sorted(chunks, key=lambda c: c.get("sequence_no", 0))
    # 重新分配连续 sequence_no, 保留原始顺序
    for seq, chunk in enumerate(sorted_chunks):
        chunk["sequence_no"] = seq
    return build_context_blocks_for_document(document_id, sorted_chunks)
