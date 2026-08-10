import re
from typing import Dict, Any, List, Optional


# Phrases that usually indicate invented operational details
HALLUCINATION_PATTERNS = [
    r"\breturn label\b",
    r"\bshipping label\b",
    r"\btracking number\b",
    r"\btrack(?:ing)? id\b",
    r"\bpickup slot\b",
    r"\bschedule(?:d)? pickup\b",
    r"\bcourier will arrive\b",
    r"\bdownload the label\b",
    r"\bprint the label\b",
    r"\bship to(?: this)? address\b",
    r"\bmailing address\b",
    r"\bwarehouse address\b",
    r"\brefund will be credited in \d+\s*(?:hours|days|business days)\b",
    r"\breplacement has been initiated\b",
    r"\brefund has been initiated\b",
    r"\breturn has been initiated\b",
]


def _tool_supports_action(tool_results: Dict[str, Any], action_keywords: List[str]) -> bool:
    if not tool_results:
        return False
    for name, result in tool_results.items():
        if not isinstance(result, dict):
            continue
        status = (result.get("status") or "").lower()
        if status not in ["success", "requires_approval"]:
            continue
        blob = f"{name} {result}".lower()
        if any(k in blob for k in action_keywords):
            return True
    return False


def find_hallucinated_claims(text: str) -> List[str]:
    hits = []
    lowered = text or ""
    for pattern in HALLUCINATION_PATTERNS:
        if re.search(pattern, lowered, flags=re.IGNORECASE):
            hits.append(pattern)
    return hits


def apply_output_guard(
    response_text: str,
    *,
    tool_results: Optional[Dict[str, Any]] = None,
    escalated: bool = False,
    blocked: bool = False,
) -> Dict[str, Any]:
    """
    Returns:
      {
        "text": sanitized_or_original,
        "flagged": bool,
        "reasons": [...]
      }
    """
    if blocked or escalated:
        return {"text": response_text, "flagged": False, "reasons": []}

    tool_results = tool_results or {}
    hits = find_hallucinated_claims(response_text)
    if not hits:
        return {"text": response_text, "flagged": False, "reasons": []}

    # Allow claims only if corresponding tools actually succeeded
    allowed = False
    if _tool_supports_action(tool_results, ["refund", "stripe_refund"]) and re.search(
        r"\brefund has been initiated\b", response_text, re.IGNORECASE
    ):
        allowed = True
    if _tool_supports_action(tool_results, ["return", "shopify_initiate_return"]) and re.search(
        r"\breturn has been initiated\b", response_text, re.IGNORECASE
    ):
        allowed = True

    if allowed:
        return {"text": response_text, "flagged": False, "reasons": []}

    safe_text = (
        "I can help with this request, but I cannot provide shipping labels, tracking numbers, "
        "pickup slots, or confirm refund/return initiation without verified system actions. "
        "Please share any required details (such as photos or order ID), and I will continue "
        "with the supported process."
    )

    return {
        "text": safe_text,
        "flagged": True,
        "reasons": hits[:5],
    }