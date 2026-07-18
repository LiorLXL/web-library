from __future__ import annotations

import re
import unicodedata
from typing import Any


TASK_TYPES = {"factual", "summary", "comparative", "matrix", "writing", "scope"}

_TASK_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("matrix", re.compile(r"文献矩阵|矩阵字段|literature\s+matrix|evidence\s+table", re.IGNORECASE)),
    ("writing", re.compile(r"(?:撰写|写一|起草|生成).*(?:综述|段落|章节|摘要)|\b(?:write|draft|compose)\b", re.IGNORECASE)),
    (
        "comparative",
        re.compile(
            r"比较|对比|区别|差异|异同|关系|关联|联系|脉络|演进|"
            r"\bcompare\b|\bcomparison\b|\brelationship\b|\brelated\b|\bversus\b|\bvs\.?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "scope",
        re.compile(
            r"知识库.*(?:有哪些|包含哪些|范围|文献清单|概览|简介|主题|定位)|"
            r"(?:这是|这个|当前).*(?:什么|怎样|哪类).*知识库|有哪些文献|列出.*文献|"
            r"\bscope\b|\blist\s+(?:the\s+)?papers\b",
            re.IGNORECASE,
        ),
    ),
    ("summary", re.compile(r"总结|概述|综述|归纳|主要(?:方法|贡献|结论)|\bsummary\b|\bsummar(?:y|ize)\b|\boverview\b", re.IGNORECASE)),
)

_QUERY_EXPANSIONS: tuple[tuple[re.Pattern[str], tuple[str, ...]], ...] = (
    (re.compile(r"方法|method(?:s|ology)?|approach", re.IGNORECASE), ("method", "methodology", "approach")),
    (re.compile(r"实验|评估|experiment(?:s|al)?|evaluation", re.IGNORECASE), ("experiment", "evaluation", "benchmark")),
    (re.compile(r"结果|性能|results?|performance", re.IGNORECASE), ("results", "performance", "metrics")),
    (re.compile(r"数据集|datasets?", re.IGNORECASE), ("dataset", "benchmark")),
    (re.compile(r"架构|框架|architectures?|framework", re.IGNORECASE), ("architecture", "framework")),
    (re.compile(r"训练|优化|training|optimization", re.IGNORECASE), ("training", "optimization")),
    (re.compile(r"贡献|创新|contributions?|novelty", re.IGNORECASE), ("contribution", "novelty")),
)

_POLITE_PREFIX_RE = re.compile(r"^(?:请问|请|麻烦|帮我|能否|可以)?\s*(?:告诉我|解释一下|分析一下)?\s*", re.IGNORECASE)
_QUESTION_SUFFIX_RE = re.compile(r"(?:是什么|有哪些|怎么样|如何|吗|呢)[？?]?$")
_ASCII_TERM_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.-]{1,}")
_CJK_TERM_RE = re.compile(r"[\u4e00-\u9fff]{2,}")


def build_query_plan(query: str, *, max_queries: int = 4) -> dict[str, Any]:
    original = str(query or "").strip()
    normalized = normalize_query(original)
    task_type = classify_task(normalized)
    candidates: list[tuple[str, str, str]] = [(normalized, "normalized_original", "")]

    for subquery in _decompose_query(normalized, task_type=task_type):
        candidates.append((subquery, "task_decomposition", "q0"))
    for expanded in _expanded_queries(normalized):
        candidates.append((expanded, "bilingual_expansion", "q0"))

    queries: list[dict[str, str]] = []
    seen: set[str] = set()
    for text, reason, parent_id in candidates:
        clean = normalize_query(text)
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        query_id = f"q{len(queries)}"
        queries.append(
            {
                "query_id": query_id,
                "parent_query_id": parent_id if query_id != "q0" else "",
                "text": clean,
                "lexical_query": lexical_query(clean),
                "reason": reason,
            }
        )
        if len(queries) >= max(1, min(int(max_queries or 4), 8)):
            break

    return {
        "original_query": original,
        "normalized_query": normalized,
        "task_type": task_type,
        "queries": queries,
    }


def normalize_query(query: str) -> str:
    value = unicodedata.normalize("NFKC", str(query or ""))
    value = value.replace("\u3000", " ")
    value = re.sub(r"[\r\n\t]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    value = _POLITE_PREFIX_RE.sub("", value).strip()
    value = _QUESTION_SUFFIX_RE.sub("", value).strip(" ，,。；;：:!?！？")
    return value


def classify_task(query: str) -> str:
    value = str(query or "").strip()
    for task_type, pattern in _TASK_PATTERNS:
        if pattern.search(value):
            return task_type
    return "factual"


def lexical_query(query: str) -> str:
    value = normalize_query(query)
    ascii_terms = _dedupe(_ASCII_TERM_RE.findall(value))
    if ascii_terms:
        return " ".join(ascii_terms[:10])

    known_terms: list[str] = []
    for pattern, _ in _QUERY_EXPANSIONS:
        match = pattern.search(value)
        if match and re.search(r"[\u4e00-\u9fff]", match.group(0)):
            known_terms.append(match.group(0))
    if known_terms:
        return " ".join(_dedupe(known_terms)[:6])

    cjk_terms = _CJK_TERM_RE.findall(re.sub(r"[，,。；;：:!?！？、]", " ", value))
    return " ".join(_dedupe(cjk_terms)[:6]) or value


def normalize_search_filters(filters: dict[str, Any] | None) -> dict[str, Any]:
    raw = filters if isinstance(filters, dict) else {}
    payload: dict[str, Any] = {}
    for key in ("year_from", "year_to"):
        value = raw.get(key)
        if value not in (None, ""):
            try:
                payload[key] = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be an integer") from None
    for key in ("authors", "venues", "item_keys", "chunk_types"):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, list):
            raise ValueError(f"filters.{key} must be a list")
        payload[key] = list(dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip()))
    if payload.get("year_from") is not None and payload.get("year_to") is not None and payload["year_from"] > payload["year_to"]:
        raise ValueError("filters.year_from must be less than or equal to filters.year_to")
    return payload


def intersect_item_keys(scoped: list[str] | None, requested: list[str]) -> list[str]:
    if scoped is None:
        return list(requested)
    allowed = set(requested)
    return [key for key in scoped if key in allowed]


def _decompose_query(query: str, *, task_type: str) -> list[str]:
    parts = [part.strip(" ，,。；;：:!?！？") for part in re.split(r"[；;]|\bversus\b|\bvs\.?\b", query, flags=re.IGNORECASE)]
    output = [part for part in parts if part and part.casefold() != query.casefold()]
    if task_type == "comparative":
        chinese = re.search(r"(?:比较|对比)\s*(.+?)\s*(?:和|与)\s*(.+?)(?:的|在|之间|$)", query, re.IGNORECASE)
        english = re.search(r"\bcompare\s+(.+?)\s+(?:and|with)\s+(.+?)(?:\s+(?:on|in|for)\b|$)", query, re.IGNORECASE)
        match = chinese or english
        if match:
            output.extend([match.group(1).strip(), match.group(2).strip()])
    return _dedupe(output)


def _expanded_queries(query: str) -> list[str]:
    ascii_entities = [term for term in _ASCII_TERM_RE.findall(query) if term.casefold() not in {"compare", "summary", "method", "methods"}]
    output: list[str] = []
    for pattern, aliases in _QUERY_EXPANSIONS:
        if not pattern.search(query):
            continue
        for alias in aliases:
            terms = [*ascii_entities[:4], alias]
            output.append(" ".join(_dedupe(terms)))
    return _dedupe(output)


def _dedupe(values: list[str] | tuple[str, ...]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = str(value or "").strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        output.append(clean)
    return output
