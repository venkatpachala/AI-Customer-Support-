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
        "disregard the rules", "bypass", "override instructions"
    ]
    return any(phrase in text.lower() for phrase in suspicious)

def is_out_of_scope(text: str) -> bool:
    text_lower = text.lower().strip()

    # Creative requests
    creative = [
        "write a poem", "write a story", "write a song", "make a song",
        "sing a song", "tell me a joke", "make a joke", "compose a",
        "generate a story", "write lyrics", "rap about", "make a rap"
    ]

    # Malicious / dangerous
    malicious = [
        "delete the database", "drop table", "delete all customers",
        "wipe the data", "hack", "sql injection", "rm -rf",
        "destroy the system", "leak customer data"
    ]

    # General knowledge / unrelated
    general = [
        "who is the prime minister", "what is the capital",
        "solve this math", "code for me", "python script",
        "recipe for", "how to cook", "weather in",
        "stock price", "bitcoin", "who won the match"
    ]

    if any(k in text_lower for k in creative):
        return True
    if any(k in text_lower for k in malicious):
        return True
    if any(k in text_lower for k in general):
        return True

    return False

def apply_guardrails(state: Dict) -> Dict:
    last_message = get_last_user_message(state.get("messages", []))

    # 1. PII
    has_pii, msg = detect_pii(last_message)
    if has_pii:
        return {
            "blocked": True,
            "error": msg
        }

    # 2. Prompt injection
    if detect_injection(last_message):
        return {
            "blocked": True,
            "error": "Potential prompt injection detected. I cannot process this request."
        }

    # 3. Out of scope / malicious
    if is_out_of_scope(last_message):
        return {
            "blocked": True,
            "error": "I can only assist with Zepto-related customer support queries such as orders, returns, refunds, delivery, and payments."
        }

    return {
        "blocked": False
    }