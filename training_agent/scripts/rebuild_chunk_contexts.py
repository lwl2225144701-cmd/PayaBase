"""回填 / 重建父上下文块(Chunk Context Blocks) — Phase 4。

幂等、分页、可重复、可中断重跑。

职责:
- 为全库 / 指定知识库 / 指定文档生成 chunk_context_blocks;
- 为每个子块补充分配 sequence_no 和 context_block_id;
- 通过 content_hash + context_version 判断是否需要重建;
- 统计 scanned / created / updated / skipped / failed。

用法:
  cd training_agent
  .venv/bin/python -m scripts.rebuild_chunk_contexts
  .venv/bin/python -m scripts.rebuild_chunk_contexts --kb-id <kb_uuid>
  .venv/bin/python -m scripts.rebuild_chunk_contexts --document-id <doc_uuid>
  .venv/bin/python -m scripts.rebuild_chunk_contexts --force
  .venv/bin/python -m scripts.rebuild_chunk_contexts --dry-run
  .venv/bin/python -m scripts.rebuild_chunk_contexts --batch-size 50

注意:
- 不依赖 Celery, 直接走同步引擎(与 indexing.py 同机制)。
- 失败不静默: 单个文档失败计入 failed 并继续, 最后打印汇总。
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from collections import defaultdict

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from core.config import settings  # noqa: E402
from core.infrastructure.db.sync_session import get_sync_engine  # noqa: E402
from core.rag.context_blocks import build_context_blocks_for_existing_chunks  # noqa: E402


def _list_documents(
    conn, kb_id: str | None, document_id: str | None, batch_size: int, last_id: str
) -> list:
    """按 id 游标分页拉取文档(keyset 分页, 支持中断重跑)。"""
    clauses = ["d.id > :last_id"]
    params: dict = {"last_id": uuid.UUID(last_id) if last_id else uuid.UUID(int=0)}
    if document_id:
        clauses.append("d.id = :doc_id")
        params["doc_id"] = uuid.UUID(document_id)
    elif kb_id:
        clauses.append("d.knowledge_base_id = :kb_id")
        params["kb_id"] = uuid.UUID(kb_id)
    params["limit"] = batch_size
    sql = text(
        """
        SELECT d.id
        FROM documents d
        WHERE """ + " AND ".join(clauses) + """
        ORDER BY d.id
        LIMIT :limit
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def _get_chunks(conn, document_id: uuid.UUID) -> list:
    """读取文档全部 chunk, 优先按 sequence_no 排序, 缺失时按 metadata 顺序, 最后按 id。"""
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.content, c.meta, c.sequence_no
            FROM chunks c
            WHERE c.document_id = :doc_id
            ORDER BY c.sequence_no, c.id
            """
        ),
        {"doc_id": document_id},
    ).mappings().all()
    chunks = []
    for r in rows:
        chunk = dict(r)
        meta = chunk.get("meta") or {}
        # 历史数据若 sequence_no 全为 0, 用 metadata 中的 chunk_index/page/start_offset 排序
        if chunk.get("sequence_no", 0) == 0 and len(rows) > 1:
            order_key = (
                meta.get("chunk_index", 0),
                meta.get("page", 0),
                meta.get("start_offset", 0),
                str(chunk["id"]),
            )
        else:
            order_key = (chunk.get("sequence_no", 0), str(chunk["id"]))
        chunk["_order_key"] = order_key
        chunks.append(chunk)

    # 按 order_key 稳定排序
    chunks.sort(key=lambda c: c["_order_key"])
    # 若 sequence_no 全为 0, 记录 warning(一次文档只打一次)
    seq_values = {c.get("sequence_no", 0) for c in chunks}
    if len(seq_values) <= 1 and len(chunks) > 1:
        print(
            f"[warn] doc={document_id} 的 chunks sequence_no 缺失或全为 0, "
            "已按 metadata(chunk_index/page/start_offset) 或 created_at/id 回退排序",
            file=sys.stderr,
        )
    return chunks


def _get_existing_blocks(conn, document_id: uuid.UUID) -> list:
    rows = conn.execute(
        text(
            """
            SELECT id, content_hash, context_version, start_sequence, end_sequence
            FROM chunk_context_blocks
            WHERE document_id = :doc_id
            ORDER BY start_sequence
            """
        ),
        {"doc_id": document_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _needs_rebuild(
    new_blocks: list[dict],
    existing: list[dict],
    context_version: str,
    force: bool,
) -> tuple[bool, str]:
    """判断文档是否需要重建父上下文块。"""
    if force:
        return True, "updated" if existing else "created"
    if not existing:
        return True, "created"
    if len(new_blocks) != len(existing):
        return True, "updated"
    # 按 start_sequence 对齐比较
    existing_sorted = sorted(existing, key=lambda b: b["start_sequence"])
    for nb, eb in zip(new_blocks, existing_sorted, strict=False):
        if (
            nb["start_sequence"] != eb["start_sequence"]
            or nb["end_sequence"] != eb["end_sequence"]
            or nb["content_hash"] != eb["content_hash"]
            or context_version != eb["context_version"]
        ):
            return True, "updated"
    return False, "skipped"


def _apply_document(conn, doc_id: uuid.UUID, context_version: str, force: bool, dry_run: bool) -> str:
    chunks = _get_chunks(conn, doc_id)
    if not chunks:
        return "skipped_no_chunk"

    _, new_blocks = build_context_blocks_for_existing_chunks(str(doc_id), chunks)
    for block in new_blocks:
        block["document_id"] = str(doc_id)

    existing = _get_existing_blocks(conn, doc_id)
    need, klass = _needs_rebuild(new_blocks, existing, context_version, force)
    if not need:
        return "skipped"

    if dry_run:
        return klass

    # 删除旧块(子块外键 SET NULL 会自动解引用)
    conn.execute(
        text("DELETE FROM chunk_context_blocks WHERE document_id = :doc_id"),
        {"doc_id": doc_id},
    )

    # 插入新块
    for block in new_blocks:
        conn.execute(
            text(
                """
                INSERT INTO chunk_context_blocks
                (id, document_id, content, start_sequence, end_sequence,
                 token_count, content_hash, context_version)
                VALUES (:id, :doc_id, :content, :start_sequence, :end_sequence,
                        :token_count, :content_hash, :context_version)
                """
            ),
            {
                "id": uuid.UUID(block["id"]),
                "doc_id": doc_id,
                "content": block["content"],
                "start_sequence": block["start_sequence"],
                "end_sequence": block["end_sequence"],
                "token_count": block["token_count"],
                "content_hash": block["content_hash"],
                "context_version": block["context_version"],
            },
        )

    # 更新 chunks 的 sequence_no 和 context_block_id
    seq_updates = defaultdict(list)  # block_id -> list of chunk ids
    for chunk in chunks:
        conn.execute(
            text("UPDATE chunks SET sequence_no = :seq WHERE id = :cid"),
            {"seq": chunk["sequence_no"], "cid": chunk["id"]},
        )
        if chunk.get("context_block_id"):
            seq_updates[chunk["context_block_id"]].append(chunk["id"])

    for block_id, chunk_ids in seq_updates.items():
        conn.execute(
            text(
                "UPDATE chunks SET context_block_id = :bid "
                "WHERE id = ANY(CAST(:cids AS uuid[]))"
            ),
            {"bid": uuid.UUID(block_id), "cids": [str(cid) for cid in chunk_ids]},
        )

    return klass


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 / 重建父上下文块(幂等、分页、可重复)")
    parser.add_argument("--kb-id", default=None, help="仅处理指定知识库")
    parser.add_argument("--document-id", default=None, help="仅处理指定文档")
    parser.add_argument("--batch-size", type=int, default=100, help="按文档分页大小(默认 100)")
    parser.add_argument("--force", action="store_true", help="忽略 content_hash, 强制重建")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    args = parser.parse_args()

    if args.kb_id and args.document_id:
        print("[warn] 同时传入 --kb-id 与 --document-id, 以 --document-id 为准", file=sys.stderr)

    context_version = settings.context_version
    engine = get_sync_engine()
    stats = {"scanned": 0, "created": 0, "updated": 0, "skipped": 0, "failed": 0}

    last_id = ""
    while True:
        with engine.connect() as conn:
            docs = _list_documents(
                conn, args.kb_id, args.document_id, args.batch_size, last_id
            )
        if not docs:
            break

        for doc in docs:
            stats["scanned"] += 1
            try:
                with engine.begin() as conn:
                    klass = _apply_document(
                        conn, doc["id"], context_version, args.force, args.dry_run
                    )
                if klass == "created":
                    stats["created"] += 1
                elif klass == "updated":
                    stats["updated"] += 1
                elif klass in ("skipped", "skipped_no_chunk"):
                    stats["skipped"] += 1
            except Exception as e:
                stats["failed"] += 1
                print(
                    f"[failed] doc={doc['id']} : {e}",
                    file=sys.stderr,
                )

        last_id = str(docs[-1]["id"])
        print(
            f"… 已扫描 {stats['scanned']} 个文档 | "
            f"created={stats['created']} updated={stats['updated']} "
            f"skipped={stats['skipped']} failed={stats['failed']}",
            flush=True,
        )
        if args.document_id:
            break

    mode = "DRY-RUN(未写库)" if args.dry_run else "WRITE"
    print("\n==== 父上下文块回填完成 ====")
    print(f"模式: {mode} | context_version={context_version}")
    print(f"scanned : {stats['scanned']}")
    print(f"created : {stats['created']}   (首次构建)")
    print(f"updated : {stats['updated']}   (hash/结构变化/--force 重建)")
    print(f"skipped : {stats['skipped']}   (已是最新, 跳过)")
    print(f"failed  : {stats['failed']}")
    return 1 if stats["failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
