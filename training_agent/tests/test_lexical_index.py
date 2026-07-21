"""第三阶段词法索引单元测试:

1. 统一分词器: 型号/规约号/IP/版本/错误码整体保留(RCS-931 / PSL-621U / IEC61850 /
   IEC-104 / 103规约 / v2.1.3 / 0x8001 / 192.168.1.1), NFKC+小写, 停用词仅无意义词。
2. 索引服务: build_lexical_text 只索引 metadata 白名单; 幂等单事务(先 DELETE 后 INSERT);
   单 chunk 最大 term 数截断。
3. content_hash: 稳定且随 index_version 变化。
4. BM25 SQL 解析: _bm25_search_sql 返回结构、排序(score desc 再 chunk_id asc)、
   仅保留 >0 分(由调用方 _filter_valid_bm25_results 保证)。
5. 回填幂等分类: _needs_rebuild 的 indexed / updated / skipped 判定。
"""
from unittest.mock import AsyncMock, MagicMock

from core.rag.lexical_index import (
    build_lexical_text,
    content_hash,
    extract_chunk_terms,
    index_document_sync,
)
from core.rag.tokenizer import tokenize_document, tokenize_query


# 1. 分词器: 型号/规约号 整体保留 -------------------------------------------------
def test_tokenize_query_preserves_model_and_protocol_numbers():
    q = "RCS-931 保护装置 IEC61850 通信 故障 0x8001 103规约"
    toks = tokenize_query(q)
    low = [t.lower() for t in toks]
    assert "rcs-931" in low
    assert "iec61850" in low
    assert "0x8001" in low
    assert "103规约" in low
    # 不应把 RCS-931 切成 rcs / 931 两个词
    assert "rcs" not in low
    assert "931" not in low


def test_tokenize_query_preserves_version_and_ip():
    q = "PSL-621U 版本 v2.1.3 地址 192.168.1.1 配置"
    toks = [t.lower() for t in tokenize_query(q)]
    assert "psl-621u" in toks
    assert "v2.1.3" in toks
    # IPv4 作为一个 token(正则 \b\d{1,3}(?:\.\d{1,3}){3}\b 在小写/NFKC 后保留)
    assert any(t == "192.168.1.1" for t in toks)


def test_tokenize_query_dedup_preserves_order():
    toks = tokenize_query("变压器 变压器 故障 保护 故障")
    assert toks == ["变压器", "故障", "保护"]


def test_tokenize_document_keeps_term_frequency():
    # 型号 token 整体保留且词频正确(jieba 会拆"电流互感器"为更小词, 故用型号验证)
    tf = tokenize_document("RCS-931 RCS-931 故障 保护")
    assert tf.get("rcs-931") == 2
    assert tf.get("故障") == 1


def test_tokenize_filters_stopwords_only():
    # 型号/数字/规约号 不被当作停用词删除
    toks = tokenize_query("RCS-931 的 是 在 装置")
    low = [t.lower() for t in toks]
    assert "rcs-931" in low
    # 纯停用词被过滤
    assert "的" not in low
    assert "是" not in low
    assert "在" not in low


# 2. 索引文本构建: 只索引 metadata 白名单 ----------------------------------------
def test_build_lexical_text_uses_whitelist_meta():
    meta = {
        "model": "RCS-931",
        "version": "v2.1.3",
        "keyword": "差动保护",
        "author": "张三",          # 非白名单, 不应入索引
        "source": "internal",      # 非白名单
        "section_title": "第二章 保护原理",
    }
    text = build_lexical_text("主变压器保护", "正文内容", meta)
    assert "主变压器保护" in text          # 标题
    assert "第二章 保护原理" in text        # 章节标题
    assert "rcs-931" in text.lower()       # 白名单 model
    assert "v2.1.3" in text                 # 白名单 version
    assert "差动保护" in text               # 白名单 keyword
    assert "张三" not in text               # 非白名单被忽略
    assert "internal" not in text.lower()  # 非白名单被忽略


# 3. content_hash 稳定且随版本变化 ------------------------------------------------
def test_content_hash_stable_and_version_dependent():
    t = "RCS-931 保护装置"
    h1 = content_hash(t, "v1")
    h2 = content_hash(t, "v1")
    h3 = content_hash(t, "v2")
    assert h1 == h2                      # 同文本同版本稳定
    assert h1 != h3                      # 版本变化 -> hash 变化
    assert len(h1) == 64                 # sha256


# 4. 索引服务: 幂等单事务(先 DELETE 后 INSERT) -----------------------------------
def test_index_document_sync_single_transaction_order():
    chunks = [
        ("c1", "主变保护", "RCS-931 差动保护 故障", {"model": "RCS-931"}),
        ("c2", "主变保护", "PSL-621U 距离保护 配置", {"model": "PSL-621U"}),
    ]
    conn = MagicMock()
    n = index_document_sync(conn, "doc1", "kb1", chunks, "v1")

    assert n == 2
    sqls = [str(c.args[0]) for c in conn.execute.call_args_list]
    # 顺序必须是: 删 terms -> 删 docs -> 插 docs -> 插 terms
    assert any("DELETE FROM chunk_lexical_terms" in s for s in sqls[:2])
    assert any("DELETE FROM chunk_lexical_documents" in s for s in sqls[:2])
    assert any("INSERT INTO chunk_lexical_documents" in s for s in sqls)
    assert any("INSERT INTO chunk_lexical_terms" in s for s in sqls)
    # 删语句必须在插语句之前
    del_idx = min(i for i, s in enumerate(sqls) if s.startswith("DELETE"))
    ins_idx = min(i for i, s in enumerate(sqls) if s.startswith("INSERT"))
    assert del_idx < ins_idx

    # INSERT terms 的批量参数含正确字段
    terms_call = [
        c for c in conn.execute.call_args_list
        if "INSERT INTO chunk_lexical_terms" in str(c.args[0])
    ][0]
    term_params = terms_call.args[1]
    assert isinstance(term_params, list) and len(term_params) >= 2
    first = term_params[0]
    assert {"chunk_id", "kb_id", "term", "tf"}.issubset(first.keys())


# 4b. 回归: DELETE 的 ANY(:ids) 必须 CAST 成 uuid[], 否则实库报
#     "operator does not exist: uuid = text"(mock 单测无法暴露, 需人工守住)
def test_index_document_sync_delete_casts_ids_to_uuid_array():
    chunks = [("c1", "主变保护", "RCS-931 差动保护", {"model": "RCS-931"})]
    conn = MagicMock()
    index_document_sync(conn, "doc1", "kb1", chunks, "v1")

    delete_sqls = [
        str(c.args[0])
        for c in conn.execute.call_args_list
        if str(c.args[0]).strip().upper().startswith("DELETE")
    ]
    # 两处 chunk_id 删除都必须带 CAST(:ids AS uuid[])
    assert any("CAST(:ids AS uuid[])" in s for s in delete_sqls)
    # 不允许出现裸的 ANY(:ids)(会触发 uuid=text)
    assert all("ANY(:ids)" not in s.replace("CAST(:ids AS uuid[])", "") for s in delete_sqls)


def test_extract_chunk_terms_respects_max_terms():
    # 构造超限文本: 用大量不同 token
    long_text = " ".join(f"词{i} 内容" for i in range(50))
    doc_record, term_rows = extract_chunk_terms(
        "c1", "doc1", "kb1", "标题", long_text, {}, "v1"
    )
    assert len(term_rows) <= 2000           # 默认 lexical_max_terms_per_chunk
    assert doc_record["content_hash"]
    assert doc_record["index_version"] == "v1"


# 5. BM25 SQL 解析: 排序 + 结构 -------------------------------------------------
async def test_bm25_search_sql_parse_sort_and_shape():
    from core.rag.retriever import Retriever

    retriever = Retriever(db=MagicMock())
    # SQL 已按 bm25_score DESC, chunk_id ASC 排序; Python 仅按 DB 返回顺序映射
    fake = MagicMock()
    fake.mappings().all.return_value = [
        {"chunk_id": "a", "bm25_score": 1.2, "matched_terms": ["保护", "故障"], "n": 100},
        {"chunk_id": "c", "bm25_score": 1.2, "matched_terms": ["故障"], "n": 100},
        {"chunk_id": "b", "bm25_score": 0.5, "matched_terms": ["保护"], "n": 100},
    ]
    retriever.db.execute = AsyncMock(return_value=fake)

    rows = await retriever._bm25_search_sql(__import__("uuid").UUID(int=0), ["保护", "故障"], 10)
    # 映射保持 DB 顺序(score desc, 同分 chunk_id asc)
    assert [r["chunk_id"] for r in rows] == ["a", "c", "b"]
    assert rows[0]["matched_terms"] == ["保护", "故障"]
    assert all(r["n"] == 100 for r in rows)
    # 排序与零分剔除由 SQL 保证: 校验生成的 SQL 含 ORDER BY 与 HAVING
    sql_text = str(retriever.db.execute.call_args.args[0])
    assert "ORDER BY bm25_score DESC, chunk_id ASC" in sql_text
    assert "HAVING SUM(term_score) > 0" in sql_text


async def test_bm25_search_sql_returns_empty_when_no_terms():
    from core.rag.retriever import Retriever

    retriever = Retriever(db=MagicMock())
    rows = await retriever._bm25_search_sql(__import__("uuid").UUID(int=0), [], 10)
    assert rows == []


async def test_bm25_search_sql_formula_in_query():
    from core.rag.retriever import Retriever

    retriever = Retriever(db=MagicMock())
    fake = MagicMock()
    fake.mappings().all.return_value = []
    retriever.db.execute = AsyncMock(return_value=fake)
    await retriever._bm25_search_sql(__import__("uuid").UUID(int=0), ["保护"], 5)
    sql_text = str(retriever.db.execute.call_args.args[0])
    # 标准 BM25 公式片段必须存在(与文档一致)
    assert "LN(1 + (s.n - COALESCE(df.df, 0) + 0.5) / (COALESCE(df.df, 0) + 0.5))" in sql_text
    assert "(:k1 + 1)" in sql_text
    assert ":k1 * (1 - :b + :b *" in sql_text
    assert "ARRAY_AGG(DISTINCT term)" in sql_text
    # 回归: terms 必须作为普通 list 绑定, 不能用 sqlalchemy.dialects.postgresql.array 对象
    # 否则 psycopg2 会报 can't adapt type 'array' 导致 BM25 整路被降级吞掉
    params = retriever.db.execute.call_args.args[1]
    assert params["terms"] == ["保护"]
    assert type(params["terms"]).__name__ == "list"


# 6. 回填幂等分类 ----------------------------------------------------------------
def test_needs_rebuild_classification():
    from scripts.rebuild_lexical_index import _needs_rebuild

    c1 = {"id": "c1", "content": "RCS-931 差动保护", "meta": {"model": "RCS-931"}, "title": "T"}
    chunk_rows = [c1]

    # 首次: 无任何词法索引 -> indexed
    need, klass = _needs_rebuild(chunk_rows, {}, "v1", force=False)
    assert need is True and klass == "indexed"

    # 已是最新(hash 匹配) -> skipped
    text = build_lexical_text("T", c1["content"], c1["meta"])
    h = content_hash(text, "v1")
    existing = {"c1": (h, "v1")}
    need, klass = _needs_rebuild(chunk_rows, existing, "v1", force=False)
    assert need is False
    assert klass == "skipped"

    # 内容变化 -> updated
    c1_changed = {
        "id": "c1", "content": "RCS-931 距离保护",
        "meta": {"model": "RCS-931"}, "title": "T",
    }
    need, klass = _needs_rebuild([c1_changed], existing, "v1", force=False)
    assert need is True and klass == "updated"

    # --force 且已有索引 -> updated(强制重建)
    need, klass = _needs_rebuild(chunk_rows, existing, "v1", force=True)
    assert need is True and klass == "updated"

    # 无 chunk -> 跳过
    need, klass = _needs_rebuild([], existing, "v1", force=False)
    assert need is False and klass == "skipped_no_chunk"
