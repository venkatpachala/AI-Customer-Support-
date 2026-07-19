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
    suspicious = ["ignore previous", "jailbreak", "system prompt", "pretend you are", "you are now"]
    return any(word in text.lower() for word in suspicious)

def apply_guardrails(state: Dict) -> Dict:
    """Main guardrails function"""
    last_message = get_last_user_message(state.get("messages", []))
    
    has_pii, msg = detect_pii(last_message)
    if has_pii:
        return {"error": msg, "blocked": True}
    
    if detect_injection(last_message):
        return {"error": "Potential prompt injection detected", "blocked": True}
    
    return {"blocked": False}