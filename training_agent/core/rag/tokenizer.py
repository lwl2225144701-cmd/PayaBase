"""统一分词器: 索引与查询共用(第三阶段词法召回)。

设计目标:
- 中文用 jieba 分词;
- Unicode NFKC 归一化 + 英文小写 + 过滤标点;
- 完整保留型号/规约号/IP/版本/错误码等(如 RCS-931, PSL-621U, IEC61850, IEC-104,
  103规约, v2.1.3, 0x8001), 这些 token 在分词前作为整体抽取, 不参与 jieba 切分;
- 查询词去重, 索引词保留词频;
- 停用词仅确定无意义词, 不删除型号/数字/规约号。
"""
import contextlib
import re
import unicodedata
from collections import Counter

import jieba

with contextlib.suppress(Exception):
    jieba.setLogLevel(60)  # CRITICAL, 静默 jieba 的词典加载日志

# 保护 token 正则(按优先级顺序匹配); 这些整体作为 token, 不再送 jieba 切分。
_PROTECT_PATTERNS = [
    r"0x[0-9a-fA-F]+",                       # 0x8001 十六进制错误码
    r"[a-zA-Z]?\d+\.\d+\.\d+(?:\.\d+)?",     # v2.1.3 / 1.2.3.4 版本号
    r"\b\d{1,3}(?:\.\d{1,3}){3}\b",          # IPv4 地址
    r"[A-Za-z]{1,6}-?\d{2,5}[A-Za-z]?",       # RCS-931 / PSL-621U / IEC61850
    r"IEC[-\s]?\d{2,5}",                      # IEC61850 / IEC-104
    r"\d{2,4}规约",                           # 103规约 / 104规约
]

# 确定无意义停用词(仅这些, 不删型号/数字/规约号/英文实词)。
_STOPWORDS = {
    # 中文
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看",
    "好", "自己", "这", "那", "与", "及", "或", "等", "被", "把", "让", "向",
    "从", "对", "为", "以", "于", "而", "之", "其", "此", "该", "各", "由",
    "将", "已", "并", "但", "若", "如", "且", "这个", "那个", "什么", "怎么", "如何",
    # 英文
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "been", "being", "this", "that", "these", "those",
    "it", "its", "as", "at", "by", "with", "from",
}

_PUNCT_RE = re.compile(
    r"[\s_/\\|\[\](){}<>\"'`~!@#$%^&*\-+=:,.;?，。、；：？！“”‘’（）《》【】…—·\u3000]+"
)


def _nfkc_lower(text: str) -> str:
    if not text:
        return ""
    return unicodedata.normalize("NFKC", text).lower()


def _extract_protect_tokens(text: str):
    """抽取保护 token, 返回 (保护token列表, 剩余待 jieba 文本)。

    关键: 多个正则可能命中同一段文本(如 IEC61850 同时被
    `[A-Za-z]{1,6}-?\\d{2,5}` 与 `IEC[-\\s]?\\d{2,5}` 命中), 必须按 **span 去重**,
    同一 span 只保留一次, 否则重复计数会抬高词频(tf)。
    去重基于 span 而非 token 文本: 不同 span 的相同 token(如 "RCS-931 RCS-931")
    仍各自保留, 词频正确为 2。
    """
    protected: list[str] = []
    accepted: list[tuple[int, int]] = []
    for pat in _PROTECT_PATTERNS:
        for m in re.finditer(pat, text, flags=re.IGNORECASE):
            s, e = m.span()
            # 跳过与已接受 span 重叠的匹配(多个正则命中同 span 只保留一次)
            if any(not (e <= a_s or s >= a_e) for (a_s, a_e) in accepted):
                continue
            accepted.append((s, e))
            protected.append(m.group(0).lower())
    accepted.sort()
    remaining_parts: list[str] = []
    last = 0
    for s, e in accepted:
        if s > last:
            remaining_parts.append(text[last:s])
        last = e
    if last < len(text):
        remaining_parts.append(text[last:])
    return protected, "".join(remaining_parts)


def _tokenize_remaining(text: str) -> list[str]:
    """对剩余文本做 jieba 分词 + 标点/停用词过滤。"""
    out: list[str] = []
    for w in jieba.cut(text):
        w = w.strip().lower()
        if not w:
            continue
        if w in _STOPWORDS:
            continue
        if _PUNCT_RE.fullmatch(w):
            continue
        # 仅保留含字母/数字/中文的词
        if not re.search(r"[\w\u4e00-\u9fff]", w):
            continue
        out.append(w)
    return out


def _extract(text: str) -> list[str]:
    text = _nfkc_lower(text)
    if not text:
        return []
    protected, remaining = _extract_protect_tokens(text)
    tokens = list(protected)
    tokens.extend(_tokenize_remaining(remaining))
    return tokens


def tokenize_query(text: str) -> list[str]:
    """查询分词: 去重、保序(用于 BM25 查询, 词频无关)。"""
    if not text:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for t in _extract(text):
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def tokenize_document(text: str) -> dict[str, int]:
    """文档分词: 保留词频 (term -> tf)。调用方负责截断最大 term 数。"""
    return dict(Counter(_extract(text)))
