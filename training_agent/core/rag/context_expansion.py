"""Phase 4 检索后上下文扩展。

只在 final top_k 确定后执行:
- 命中子块优先补充父上下文块;
- 无父块时补充相邻子块;
- 合并重叠上下文, 向 LLM 传递去重后的 context groups。

禁止: 重新参与召回/RRF/Rerank/threshold, 补回淘汰结果, 修改 final_score/final_rank。
"""

import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ContextGroup:
    """去重后的上下文组, 作为 LLM 上下文的实际单元。"""

    group_id: str
    document_id: str
    document_title: str
    parent_context_id: str | None
    context_content: str
    child_chunk_ids: list[str] = field(default_factory=list)
    child_results: list = field(default_factory=list)  # RetrievedChunk 引用
    min_final_rank: int = 0
    context_source: str = "child"
    context_char_count: int = 0
    context_truncated: bool = False


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


def _concat_chunks(chunks: list[dict]) -> tuple[str, list[str]]:
    """按顺序拼接 chunk content, 只做确定性前后缀重叠删除。"""
    if not chunks:
        return "", []
    parts = [chunks[0]["content"]]
    for prev, nxt in zip(chunks, chunks[1:], strict=False):
        parts.append(_remove_exact_overlap(prev["content"], nxt["content"]))
    return "".join(parts), [str(c["id"]) for c in chunks]


def _find_hit_window(full_text: str, hit_text: str) -> tuple[int, int]:
    """在 full_text 中定位 hit_text, 返回 (start, end)。找不到取全文中间。"""
    hit = (hit_text or "").strip()
    if not hit:
        mid = len(full_text) // 2
        return mid, mid
    idx = full_text.find(hit)
    if idx >= 0:
        return idx, idx + len(hit)
    prefix = hit[:60]
    idx = full_text.find(prefix)
    if idx >= 0:
        return idx, idx + len(prefix)
    mid = len(full_text) // 2
    return mid, mid


def _truncate_around_hit(
    full_text: str,
    hit_start: int,
    hit_end: int,
    max_chars: int,
) -> tuple[str, bool]:
    """以命中区间为中心截断到 max_chars, 返回 (text, truncated)。"""
    if len(full_text) <= max_chars:
        return full_text, False

    hit_len = hit_end - hit_start
    # 优先保证命中区间完整
    if hit_len >= max_chars:
        return full_text[hit_start : hit_start + max_chars], True

    half = (max_chars - hit_len) // 2
    start = max(0, hit_start - half)
    end = min(len(full_text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)
    return full_text[start:end], True


def _build_group(doc_id: str, parent_id: str | None, member_results: list) -> ContextGroup:
    """把一组命中结果合并为一个上下文组。"""
    first = member_results[0]
    g = ContextGroup(
        group_id=f"{doc_id}:{parent_id or 'none'}:{len(member_results)}",
        document_id=doc_id,
        document_title=first.document_title,
        parent_context_id=parent_id,
        context_content="",
        context_source=getattr(first, "context_source", "child") or "child",
        min_final_rank=min((r.final_rank or 0) for r in member_results),
    )
    for r in member_results:
        g.child_results.append(r)
        g.child_chunk_ids.append(r.chunk_id)
        rc = r.context_content or r.content or ""
        if not g.context_content:
            g.context_content = rc
        else:
            g.context_content = g.context_content + _remove_exact_overlap(g.context_content, rc)
    g.context_char_count = len(g.context_content)
    g.context_truncated = any(getattr(r, "context_truncated", False) for r in member_results)
    return g


def assemble_context_groups(results: list) -> list[ContextGroup]:
    """合并重叠上下文, 返回去重后的上下文组(按 min_final_rank 排序)。

    规则:
    - 同一 parent context 只生成一个上下文组;
    - 相邻窗口重叠时合并(按 sequence 区间合并);
    - 不同文档永远不合并;
    - 保留全部命中子块 ID 与各自分数/排名;
    - 整次请求超 context_total_max_chars 时优先保留靠前组(更优 rank),
      从尾部(最远相邻块)截断。
    """
    if not results:
        return []

    adjacent_window = settings.context_adjacent_window
    total_max = settings.context_total_max_chars

    # 1) 收集区间: 有父块按 parent_id 归类, 无父块按 sequence 窗口区间
    by_parent: dict[tuple, list] = {}
    by_interval: dict[str, list] = {}
    for r in results:
        doc_id = r.document_id
        parent_id = getattr(r, "parent_context_id", None)
        seq = getattr(r, "sequence_no", None)
        if parent_id:
            by_parent.setdefault((doc_id, str(parent_id)), []).append(r)
        else:
            if seq is not None:
                lo, hi = seq - adjacent_window, seq + adjacent_window
            else:
                # 降级: 无父块且无 seq, 每个结果独立成组
                lo = hi = hash(r.chunk_id) & 0x7FFFFFFF
            by_interval.setdefault(doc_id, []).append((lo, hi, r))

    groups: list[ContextGroup] = []

    # 2) 同父块直接合并为一组
    for (doc_id, parent_id), members in by_parent.items():
        groups.append(_build_group(doc_id, parent_id, members))

    # 3) 无父块: 同文档内按 sequence 区间合并(重叠或相邻即合并)
    for doc_id, intervals in by_interval.items():
        intervals.sort(key=lambda x: x[0])
        merged: list[list] = []
        for lo, hi, r in intervals:
            if merged and lo <= merged[-1][1] + 1:
                merged[-1][1] = max(merged[-1][1], hi)
                merged[-1][2].append(r)
            else:
                merged.append([lo, hi, [r]])
        for _lo, _hi, members in merged:
            groups.append(_build_group(doc_id, None, members))

    # 4) 按 min_final_rank 排序
    groups.sort(key=lambda g: g.min_final_rank)

    # 5) 整次预算截断(优先保留靠前组=更优 rank; 组内从尾部=远相邻块截断)
    total = 0
    for g in groups:
        if total + g.context_char_count > total_max:
            remain = max(0, total_max - total)
            if remain < g.context_char_count:
                g.context_content = g.context_content[:remain]
                g.context_char_count = len(g.context_content)
                g.context_truncated = True
        total += g.context_char_count

    return groups


async def expand_results(
    db: AsyncSession,
    results: list,
) -> tuple[list, dict]:
    """为 final top_k 结果加载并填充上下文信息。

    Returns:
        (results, ctx_stats)
        - results: 每个 RetrievedChunk 被写入 context_content / parent_context_id /
          context_chunk_ids / adjacent_before_ids / adjacent_after_ids /
          context_source / context_char_count / context_truncated。
        - ctx_stats: 供 timings 使用的统计字典。

    关闭 context_expansion_enabled 时原样返回, 行为与第三阶段一致。
    """
    t0 = time.time()
    ctx_stats: dict = {
        "context_expansion_enabled": settings.context_expansion_enabled,
        "parent_context_hit_count": 0,
        "adjacent_chunk_count": 0,
        "context_group_count_before_merge": 0,
        "context_group_count_after_merge": 0,
        "context_duplicate_removed_count": 0,
        "context_truncated_count": 0,
        "context_total_chars": 0,
        "context_expand_ms": 0,
    }

    if not results or not settings.context_expansion_enabled:
        ctx_stats["context_expand_ms"] = int((time.time() - t0) * 1000)
        return results, ctx_stats

    doc_ids = {r.document_id for r in results if r.document_id}
    if not doc_ids:
        ctx_stats["context_expand_ms"] = int((time.time() - t0) * 1000)
        return results, ctx_stats

    doc_ids_uuid = [uuid.UUID(d) for d in doc_ids]
    chunk_rows = await db.execute(
        text(
            "SELECT id, document_id, sequence_no, context_block_id, content "
            "FROM chunks "
            "WHERE document_id = ANY(CAST(:doc_ids AS uuid[])) "
            "ORDER BY document_id, sequence_no, id"
        ),
        {"doc_ids": [str(d) for d in doc_ids_uuid]},
    )
    block_rows = await db.execute(
        text(
            "SELECT id, document_id, content, start_sequence, end_sequence "
            "FROM chunk_context_blocks "
            "WHERE document_id = ANY(CAST(:doc_ids AS uuid[])) "
            "ORDER BY document_id, start_sequence"
        ),
        {"doc_ids": [str(d) for d in doc_ids_uuid]},
    )

    chunks_by_doc: dict[str, dict[int, dict]] = {}
    seq_by_chunk: dict[str, int] = {}
    block_by_id: dict[str, dict] = {}
    for r in chunk_rows.mappings().all():
        d = dict(r)
        doc_id = str(d["document_id"])
        seq = int(d["sequence_no"])
        chunks_by_doc.setdefault(doc_id, {})[seq] = d
        seq_by_chunk[str(d["id"])] = seq
    for r in block_rows.mappings().all():
        b = dict(r)
        block_by_id[str(b["id"])] = b

    adjacent_window = settings.context_adjacent_window
    max_chars_per = settings.context_max_chars_per_result

    expanded: list = []
    for result in results:
        hit_chunk_id = result.chunk_id
        hit_seq = seq_by_chunk.get(hit_chunk_id)
        doc_id = result.document_id
        doc_chunks = chunks_by_doc.get(doc_id, {})

        hit_chunk = doc_chunks.get(hit_seq) if hit_seq is not None else None
        parent_block = None
        if hit_chunk and hit_chunk.get("context_block_id"):
            parent_block = block_by_id.get(str(hit_chunk["context_block_id"]))

        ordered_chunks: list[dict] = []
        adjacent_before: list[str] = []
        adjacent_after: list[str] = []

        if settings.context_parent_enabled and parent_block is not None:
            ctx_stats["parent_context_hit_count"] += 1
            context_source = "parent"
            start_seq = int(parent_block["start_sequence"])
            end_seq = int(parent_block["end_sequence"])
            for s in range(start_seq, end_seq + 1):
                if s in doc_chunks:
                    ordered_chunks.append(doc_chunks[s])
            for w in range(1, adjacent_window + 1):
                s = start_seq - w
                if s in doc_chunks:
                    ordered_chunks.insert(0, doc_chunks[s])
                    adjacent_before.append(str(doc_chunks[s]["id"]))
                s = end_seq + w
                if s in doc_chunks:
                    ordered_chunks.append(doc_chunks[s])
                    adjacent_after.append(str(doc_chunks[s]["id"]))
        else:
            context_source = "child"
            if hit_chunk is not None:
                ordered_chunks = [hit_chunk]
            else:
                ordered_chunks = [{"id": hit_chunk_id, "content": result.content}]
            if hit_seq is not None:
                for w in range(1, adjacent_window + 1):
                    s = hit_seq - w
                    if s in doc_chunks:
                        ordered_chunks.insert(0, doc_chunks[s])
                        adjacent_before.append(str(doc_chunks[s]["id"]))
                    s = hit_seq + w
                    if s in doc_chunks:
                        ordered_chunks.append(doc_chunks[s])
                        adjacent_after.append(str(doc_chunks[s]["id"]))

        if not ordered_chunks:
            context_text = result.content
            context_source = "child"
            chunk_ids = [hit_chunk_id]
            truncated = False
        else:
            full_text, chunk_ids = _concat_chunks(ordered_chunks)
            hit_content = hit_chunk["content"] if hit_chunk is not None else result.content
            h_start, h_end = _find_hit_window(full_text, hit_content)
            context_text, truncated = _truncate_around_hit(
                full_text, h_start, h_end, max_chars_per
            )
            if adjacent_before or adjacent_after:
                context_source = f"{context_source}_adjacent"

        # 写回结果对象(不修改 final_score / final_rank / score_type)
        result.context_content = context_text
        result.sequence_no = hit_seq
        result.context_source = context_source
        result.parent_context_id = (
            str(parent_block["id"]) if parent_block is not None else None
        )
        result.context_chunk_ids = chunk_ids
        result.adjacent_before_ids = adjacent_before
        result.adjacent_after_ids = adjacent_after
        result.context_char_count = len(context_text)
        result.context_truncated = truncated

        ctx_stats["adjacent_chunk_count"] += len(adjacent_before) + len(adjacent_after)
        if truncated:
            ctx_stats["context_truncated_count"] += 1
        expanded.append(result)

    # 组内合并统计(供 timings)
    groups = assemble_context_groups(expanded)
    ctx_stats["context_group_count_before_merge"] = len(expanded)
    ctx_stats["context_group_count_after_merge"] = len(groups)
    ctx_stats["context_duplicate_removed_count"] = len(expanded) - len(groups)
    ctx_stats["context_total_chars"] = sum(g.context_char_count for g in groups)
    ctx_stats["context_expand_ms"] = int((time.time() - t0) * 1000)

    return expanded, ctx_stats
