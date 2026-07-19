import re
from typing import Dict, Tuple
from common.messages import get_last_user_message

def detect_pii(text: str) -> Tuple[bool, str]:
    patterns = {
        "email": r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b',
        "phone": r'\b\d{10}\b',
        "card": r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'
    }
    for name, pattern in patterns.items():
        if re.search(pattern, text):
            return True, f"PII detected: {name}"
    return False, ""

def detect_injection(text: str) -> bool:
    suspicious = [
        "ignore previous", "jailbreak", "system prompt",
        "pretend you are", "you are now", "act as",
        "disregard the rules", "bypass"
    ]
    return any(phrase in text.lower() for phrase in suspicious)

def is_out_of_scope(text: str) -> bool:
    """
    Reject queries that are clearly outside Zepto customer support scope.
    """
    out_of_scope_keywords = [
        "write a poem", "write a story", "tell me a joke",
        "who is the prime minister", "what is the capital",
        "solve this math", "code for me", "python script",
        "recipe for", "how to cook", "weather in",
        "stock price", "bitcoin", "who won the match",
        "personal advice", "relationship advice",
        "medical advice", "legal advice"
    ]
    
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in out_of_scope_keywords)

def apply_guardrails(state: Dict) -> Dict:
    last_message = get_last_user_message(state.get("messages", []))

    # 1. PII check
    has_pii, msg = detect_pii(last_message)
    if has_pii:
        return {"error": msg, "blocked": True}

    # 2. Prompt injection
    if detect_injection(last_message):
        return {"error": "Potential prompt injection detected", "blocked": True}

    # 3. Out of scope check
    if is_out_of_scope(last_message):
        return {
            "error": "I can only assist with Zepto-related customer support queries such as orders, returns, refunds, delivery, and payments.",
            "blocked": True
        }

    return {"blocked": False}