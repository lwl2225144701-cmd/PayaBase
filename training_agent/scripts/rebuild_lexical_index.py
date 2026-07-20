"""回填 / 重建词法索引(Lexical Index) — 第三阶段。

幂等、分页、可重复、可中断重跑。

职责：
- 为全库 / 指定知识库 / 指定文档构建 chunk_lexical_documents + chunk_lexical_terms；
- 通过 content_hash + index_version 判断是否需要重建(命中则跳过, 支持中断后重跑)；
- 统计 scanned / indexed / updated / skipped / failed。

用法:
  cd training_agent
  # 全库重建(可重复, 已是最新的 chunk 会被跳过)
  .venv/bin/python scripts/rebuild_lexical_index.py
  # 仅指定知识库
  .venv/bin/python scripts/rebuild_lexical_index.py --kb-id <kb_uuid>
  # 仅指定文档
  .venv/bin/python scripts/rebuild_lexical_index.py --document-id <doc_uuid>
  # 强制全量重建(忽略 hash)
  .venv/bin/python scripts/rebuild_lexical_index.py --force
  # 只统计不写库
  .venv/bin/python scripts/rebuild_lexical_index.py --dry-run
  # 调整批大小(按文档分页)
  .venv/bin/python scripts/rebuild_lexical_index.py --batch-size 50

注意:
- 不依赖 Celery, 直接走同步引擎(与 indexing.py 同机制)。
- 表结构与后端 ensure_runtime_schema 一致; 脚本启动时会自建(IF NOT EXISTS)。
- 失败不静默: 单个文档失败计入 failed 并继续, 最后打印汇总。
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text  # noqa: E402

from core.config import settings  # noqa: E402
from core.infrastructure.db.sync_session import get_sync_engine  # noqa: E402
from core.rag.lexical_index import (  # noqa: E402
    build_lexical_text,
    content_hash,
    index_document_sync,
)

CREATE_TABLES = [
    """
    CREATE TABLE IF NOT EXISTS chunk_lexical_documents (
        chunk_id UUID PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
        knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        token_count INTEGER DEFAULT 0,
        content_hash VARCHAR(64) NOT NULL,
        index_version VARCHAR(32) NOT NULL DEFAULT 'v1',
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS chunk_lexical_terms (
        chunk_id UUID NOT NULL REFERENCES chunks(id) ON DELETE CASCADE,
        knowledge_base_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
        term VARCHAR(255) NOT NULL,
        term_frequency INTEGER DEFAULT 1,
        PRIMARY KEY (chunk_id, knowledge_base_id, term)
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_chunk_lexical_terms_kb_term "
    "ON chunk_lexical_terms (knowledge_base_id, term)",
    "CREATE INDEX IF NOT EXISTS ix_chunk_lexical_terms_chunk "
    "ON chunk_lexical_terms (chunk_id)",
]


def _ensure_tables(conn) -> None:
    for sql in CREATE_TABLES:
        conn.execute(text(sql))
    conn.commit()


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
        SELECT d.id, d.knowledge_base_id, d.title
        FROM documents d
        WHERE """ + " AND ".join(clauses) + """
        ORDER BY d.id
        LIMIT :limit
        """
    )
    rows = conn.execute(sql, params).mappings().all()
    return [dict(r) for r in rows]


def _get_existing_hashes(conn, document_id: uuid.UUID) -> dict:
    """返回 {chunk_id_str: (content_hash, index_version)}。"""
    rows = conn.execute(
        text(
            "SELECT chunk_id, content_hash, index_version "
            "FROM chunk_lexical_documents WHERE document_id = :doc_id"
        ),
        {"doc_id": document_id},
    ).mappings().all()
    return {str(r["chunk_id"]): (r["content_hash"], r["index_version"]) for r in rows}


def _get_chunks(conn, document_id: uuid.UUID) -> list:
    rows = conn.execute(
        text(
            """
            SELECT c.id, c.content, c.meta
            FROM chunks c
            WHERE c.document_id = :doc_id
            ORDER BY c.id
            """
        ),
        {"doc_id": document_id},
    ).mappings().all()
    return [dict(r) for r in rows]


def _needs_rebuild(
    chunk_rows: list, existing: dict, index_version: str, force: bool
) -> tuple[bool, str]:
    """返回 (是否需要重建, 分类: indexed | updated)。

    indexed: 该文档此前无任何词法索引(首次构建)。
    updated: 此前有索引, 但 hash 变化 / chunk 集变化 / --force。
    """
    if not chunk_rows:
        # 无 chunk 的文档无需构建
        return False, "skipped_no_chunk"
    if force:
        if not existing:
            return True, "indexed"
        return True, "updated"
    if not existing:
        return True, "indexed"
    for c in chunk_rows:
        cid = str(c["id"])
        title = c.get("title") or ""
        text = build_lexical_text(title, c["content"], c.get("meta") or {})
        h = content_hash(text, index_version)
        prior = existing.get(cid)
        if prior is None or prior != (h, index_version):
            return True, "updated"
    return False, "skipped"


def process(conn, doc: dict, index_version: str, force: bool, dry_run: bool) -> str:
    """处理单个文档。返回 indexed / updated / skipped / skipped_no_chunk。"""
    doc_id = doc["id"]
    kb_id = doc["knowledge_base_id"]
    title = doc["title"]
    chunk_rows = _get_chunks(conn, doc_id)
    # 注入文档标题: index_document_sync 用文档标题构建索引文本,
    # 这里必须一致, 否则 content_hash 永远不匹配 → 每次都判为 updated。
    for c in chunk_rows:
        c["title"] = title
    existing = _get_existing_hashes(conn, doc_id) if not force else {}
    need, klass = _needs_rebuild(chunk_rows, existing, index_version, force)
    if not need:
        return klass  # skipped / skipped_no_chunk

    if dry_run:
        return klass  # 统计分类一致, 但不写库

    lexical_chunks = [
        (str(c["id"]), title, c["content"], c.get("meta") or {}) for c in chunk_rows
    ]
    index_document_sync(conn, str(doc_id), str(kb_id), lexical_chunks, index_version)
    conn.commit()
    return klass


def main() -> int:
    parser = argparse.ArgumentParser(description="回填 / 重建词法索引(幂等、分页、可重复)")
    parser.add_argument("--kb-id", default=None, help="仅处理指定知识库")
    parser.add_argument("--document-id", default=None, help="仅处理指定文档")
    parser.add_argument("--batch-size", type=int, default=100, help="按文档分页大小(默认 100)")
    parser.add_argument("--force", action="store_true", help="忽略 content_hash, 强制重建")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写库")
    parser.add_argument("--index-version", default=settings.lexical_index_version,
                        help=f"索引版本(默认 {settings.lexical_index_version})")
    args = parser.parse_args()

    if args.kb_id and args.document_id:
        print("[warn] 同时传入 --kb-id 与 --document-id, 以 --document-id 为准", file=sys.stderr)

    index_version = args.index_version
    engine = get_sync_engine()
    stats = {"scanned": 0, "indexed": 0, "updated": 0, "skipped": 0, "failed": 0}

    with engine.begin() as conn:
        _ensure_tables(conn)

    last_id = ""
    processed_docs = 0
    while True:
        with engine.connect() as conn:
            docs = _list_documents(
                conn, args.kb_id, args.document_id, args.batch_size, last_id
            )
        if not docs:
            break

        for doc in docs:
            stats["scanned"] += 1
            processed_docs += 1
            try:
                with engine.begin() as conn:
                    klass = process(conn, doc, index_version, args.force, args.dry_run)
                if klass == "indexed":
                    stats["indexed"] += 1
                elif klass == "updated":
                    stats["updated"] += 1
                elif klass in ("skipped", "skipped_no_chunk"):
                    stats["skipped"] += 1
            except Exception as e:  # 单文档失败不阻断整体
                stats["failed"] += 1
                print(
                    f"[failed] doc={doc['id']} kb={doc.get('knowledge_base_id')} : {e}",
                    file=sys.stderr,
                )

        last_id = str(docs[-1]["id"])
        print(
            f"… 已扫描 {stats['scanned']} 个文档 | "
            f"indexed={stats['indexed']} updated={stats['updated']} "
            f"skipped={stats['skipped']} failed={stats['failed']}",
            flush=True,
        )
        if args.document_id:
            break  # 单文档模式无需翻页

    mode = "DRY-RUN(未写库)" if args.dry_run else "WRITE"
    print("\n==== 词法索引回填完成 ====")
    print(f"模式: {mode} | index_version={index_version}")
    print(f"scanned : {stats['scanned']}")
    print(f"indexed : {stats['indexed']}   (首次构建)")
    print(f"updated : {stats['updated']}   (hash 变化/--force 重建)")
    print(f"skipped : {stats['skipped']}   (已是最新, 跳过)")
    print(f"failed  : {stats['failed']}")
    return 1 if stats["failed"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
