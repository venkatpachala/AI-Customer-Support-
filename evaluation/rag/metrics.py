"""Frozen retrieval metrics. Ranks are 1-based. Page number is never a hit."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


def clause_in_text(text: str, gold_clause: str) -> bool:
    """True when the gold clause stands alone, including a 'clause N' form.

    A shorter number must not match a longer one: 8.1 is not 8.1.2.
    """
    gold = norm(str(gold_clause or "")).rstrip(".")
    if not gold:
        return False
    body = norm(text)
    escaped = re.escape(gold)
    # A clause may end with a period in the PDF ("8.1.1.1.") without becoming 8.1.1.1.2.
    pattern = rf"(?<![\d.]){escaped}(?!\.\d)(?!\d)"
    if re.search(pattern, body):
        return True
    return re.search(rf"clause\s+{escaped}(?!\.\d)(?!\d)", body) is not None


def is_gold_hit(chunk: Dict[str, Any], gold_clause: str) -> bool:
    gold = str(gold_clause or "").strip().rstrip(".")
    if not gold:
        return False
    meta = str(chunk.get("clause") or "").strip().rstrip(".")
    if meta == gold:
        return True
    return clause_in_text(str(chunk.get("content") or ""), gold)


def first_gold_rank(chunks: Sequence[Dict[str, Any]], gold_clause: str) -> Optional[int]:
    for index, chunk in enumerate(chunks, start=1):
        if is_gold_hit(chunk, gold_clause):
            return index
    return None


def recall_at(rank: Optional[int], k: int) -> float:
    if rank is not None and rank <= k:
        return 1.0
    return 0.0


def reciprocal_rank(rank: Optional[int]) -> float:
    if rank is None or rank < 1:
        return 0.0
    return 1.0 / float(rank)


def mean(values: Iterable[float]) -> float:
    rows = list(values)
    if not rows:
        return 0.0
    return sum(rows) / len(rows)


def duplicate_key(chunk: Dict[str, Any]) -> str:
    source_id = str(chunk.get("source_id") or "")
    clause = str(chunk.get("clause") or "").strip()
    prefix = norm(str(chunk.get("content") or ""))[:200]
    return f"{source_id}|{clause}|{prefix}"


def query_has_duplicate(chunks: Sequence[Dict[str, Any]], k: int = 5) -> bool:
    seen = set()
    for chunk in list(chunks)[:k]:
        key = duplicate_key(chunk)
        if key in seen:
            return True
        seen.add(key)
    return False


def duplicate_rate_at_5(rankings: Sequence[Sequence[Dict[str, Any]]]) -> float:
    if not rankings:
        return 0.0
    flags = [1.0 if query_has_duplicate(chunks, 5) else 0.0 for chunks in rankings]
    return mean(flags)


def chunk_leaks(chunk: Dict[str, Any], tenant_id: str, *, tenant_filter_on: bool) -> Optional[bool]:
    """Missing tenant_id is a leak once the tenant filter exists. Otherwise it is not measured."""
    raw = chunk.get("tenant_id")
    if raw is None or str(raw).strip() == "":
        if not tenant_filter_on:
            return None
        return True
    return str(raw).strip() != str(tenant_id or "").strip()


def tenant_leak_rate(
    rankings: Sequence[Sequence[Dict[str, Any]]],
    tenant_id: str,
    *,
    tenant_filter_on: bool,
    k: int = 5,
) -> Any:
    if not tenant_filter_on:
        return "not_measured"
    checked = 0
    leaked = 0
    for chunks in rankings:
        for chunk in list(chunks)[:k]:
            checked += 1
            if chunk_leaks(chunk, tenant_id, tenant_filter_on=True):
                leaked += 1
    if checked == 0:
        return 0.0
    return leaked / checked


def fact_supported(fact: str, chunk_text: str) -> bool:
    """A gold fact, or a stem of its content words, appears in the retrieved chunk."""
    fact_norm = norm(fact)
    body = norm(chunk_text)
    if not fact_norm:
        return False
    if fact_norm in body:
        return True
    stems = [token[:5] for token in re.findall(r"[a-z0-9]{5,}", fact_norm)]
    if not stems:
        return False
    found = sum(1 for stem in stems if stem in body)
    return found / len(stems) >= 0.6


def facts_supported(facts: Sequence[str], chunk_text: str) -> bool:
    if not facts:
        return False
    return all(fact_supported(fact, chunk_text) for fact in facts)


def cites_clause(reply: str, gold_clause: str) -> bool:
    return clause_in_text(reply or "", gold_clause)


def claims_refund_processed(reply: str) -> bool:
    return "refund has been processed" in norm(reply)


def abstains(reply: str) -> bool:
    text = norm(reply)
    phrases = (
        "does not state",
        "do not state",
        "doesn't state",
        "not stated",
        "policy does not",
        "terms do not",
        "terms does not",
        "not in the policy",
        "not in the terms",
        "no information in the policy",
    )
    return any(phrase in text for phrase in phrases)
