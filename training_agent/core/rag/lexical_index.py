"""词法索引服务: 幂等、单事务、批量写入与清理(第三阶段)。

- 通过 content_hash + index_version 判断是否需要重建(调用方比对);
- 同一事务中删除旧词项并批量写入新词项(禁止逐词单条 SQL);
- 限制单 Chunk 文本长度和最大 term 数量;
- 外键级联删除保证删 chunk/document/kb 时词法索引自动清理, 这里再显式删除并记日志。
"""
import hashlib
import logging

from sqlalchemy import text

from core.config import settings
from core.rag.tokenizer import tokenize_document

logger = logging.getLogger(__name__)

# metadata 白名单: 只索引这些 key(不索引整个 metadata JSON)。
META_INDEX_WHITELIST = [
    "model", "model_no", "device_model", "version", "versions",
    "keyword", "keywords", "standard", "protocol", "protocol_no",
]


def build_lexical_text(title, content, meta) -> str:
    """构建索引文本: 文档标题 + 章节标题 + Chunk 正文 + metadata 白名单(model/version/keyword)。"""
    parts: list[str] = []
    if title:
        parts.append(title)
    if meta:
        section = meta.get("section_title") or meta.get("heading") or meta.get("chapter")
        if section:
            parts.append(section)
        for k in META_INDEX_WHITELIST:
            v = meta.get(k)
            if isinstance(v, (list, tuple, set)):
                parts.extend(str(x) for x in v if x)
            elif v:
                parts.append(str(v))
    if content:
        parts.append(content)
    return "\n".join(p for p in parts if p)


def content_hash(text: str, index_version: str) -> str:
    return hashlib.sha256(f"{index_version}::{text}".encode()).hexdigest()


def extract_chunk_terms(chunk_id, document_id, kb_id, title, content, meta, index_version):
    """返回 (doc_record, term_rows)。

    doc_record: dict for chunk_lexical_documents
    term_rows: list of dict {chunk_id, kb_id, term, tf}
    """
    text = build_lexical_text(title, content, meta)[: settings.lexical_max_text_length]
    tf = tokenize_document(text)
    # 限制单 chunk 最大 term 数(截断超长文本)
    if len(tf) > settings.lexical_max_terms_per_chunk:
        tf = dict(list(tf.items())[: settings.lexical_max_terms_per_chunk])
    token_count = sum(tf.values())
    doc_record = {
        "chunk_id": chunk_id,
        "knowledge_base_id": kb_id,
        "document_id": document_id,
        "token_count": token_count,
        "content_hash": content_hash(text, index_version),
        "index_version": index_version,
    }
    term_rows = [
        {"chunk_id": chunk_id, "kb_id": kb_id, "term": t, "tf": f}
        for t, f in tf.items()
    ]
    return doc_record, term_rows


def index_document_sync(conn, document_id, kb_id, chunks, index_version=None):
    """幂等索引一个文档的所有 chunk(同步连接, 同一事务)。

    chunks: list of (chunk_id, title, content, meta)。
    单事务: 删除该文档旧词项 → 批量写入新词项。
    """
    index_version = index_version or settings.lexical_index_version
    chunk_ids = [c[0] for c in chunks]
    if not chunk_ids:
        return 0
    # 1) 删除旧(同一事务)
    conn.execute(
        text("DELETE FROM chunk_lexical_terms WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    )
    conn.execute(
        text("DELETE FROM chunk_lexical_documents WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    )
    # 2) 批量构建
    doc_records = []
    term_rows = []
    for chunk_id, title, content, meta in chunks:
        doc_record, terms = extract_chunk_terms(
            chunk_id, document_id, kb_id, title, content, meta, index_version
        )
        doc_records.append(doc_record)
        term_rows.extend(terms)
    # 3) 批量写入(禁止逐词单条 SQL)
    if doc_records:
        conn.execute(
            text(
                "INSERT INTO chunk_lexical_documents "
                "(chunk_id, knowledge_base_id, document_id, token_count, "
                " content_hash, index_version) "
                "VALUES (:chunk_id, :knowledge_base_id, :document_id, "
                " :token_count, :content_hash, :index_version)"
            ),
            doc_records,
        )
    if term_rows:
        conn.execute(
            text(
                "INSERT INTO chunk_lexical_terms "
                "(chunk_id, knowledge_base_id, term, term_frequency) "
                "VALUES (:chunk_id, :kb_id, :term, :tf)"
            ),
            term_rows,
        )
    return len(doc_records)


async def delete_by_document_async(db, document_id):
    """显式清理文档词法索引(async); 失败记录日志(不静默)。FK 级联为兜底。"""
    try:
        await db.execute(
            text("DELETE FROM chunk_lexical_terms WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
        await db.execute(
            text("DELETE FROM chunk_lexical_documents WHERE document_id = :doc_id"),
            {"doc_id": document_id},
        )
    except Exception as e:
        logger.error(f"[LexicalIndex] 删除文档词法索引失败 doc={document_id}: {e}")
        raise


async def delete_by_kb_async(db, kb_id):
    """显式清理知识库词法索引(async); 失败记录日志。"""
    try:
        await db.execute(
            text("DELETE FROM chunk_lexical_terms WHERE knowledge_base_id = :kb_id"),
            {"kb_id": kb_id},
        )
        await db.execute(
            text("DELETE FROM chunk_lexical_documents WHERE knowledge_base_id = :kb_id"),
            {"kb_id": kb_id},
        )
    except Exception as e:
        logger.error(f"[LexicalIndex] 删除知识库词法索引失败 kb={kb_id}: {e}")
        raise


async def index_document_async(db, document_id, kb_id, chunks, index_version=None):
    """异步版 index_document_sync(用于 ORM AsyncSession 的 Repository 层替换/编辑)。"""
    index_version = index_version or settings.lexical_index_version
    chunk_ids = [c[0] for c in chunks]
    if not chunk_ids:
        return 0
    await db.execute(
        text("DELETE FROM chunk_lexical_terms WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    )
    await db.execute(
        text("DELETE FROM chunk_lexical_documents WHERE chunk_id = ANY(:ids)"),
        {"ids": chunk_ids},
    )
    doc_records = []
    term_rows = []
    for chunk_id, title, content, meta in chunks:
        doc_record, terms = extract_chunk_terms(
            chunk_id, document_id, kb_id, title, content, meta, index_version
        )
        doc_records.append(doc_record)
        term_rows.extend(terms)
    if doc_records:
        await db.execute(
            text(
                "INSERT INTO chunk_lexical_documents "
                "(chunk_id, knowledge_base_id, document_id, token_count, "
                " content_hash, index_version) "
                "VALUES (:chunk_id, :knowledge_base_id, :document_id, "
                " :token_count, :content_hash, :index_version)"
            ),
            doc_records,
        )
    if term_rows:
        await db.execute(
            text(
                "INSERT INTO chunk_lexical_terms "
                "(chunk_id, knowledge_base_id, term, term_frequency) "
                "VALUES (:chunk_id, :kb_id, :term, :tf)"
            ),
            term_rows,
        )
    return len(doc_records)
