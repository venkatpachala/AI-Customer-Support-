import json
import requests
import time
from pathlib import Path
from datetime import datetime

API_URL = "http://127.0.0.1:8000/chat"
GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.json"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

def call_api(query: str, customer_id: str = "eval_user", tenant_id: str = "zepto"):
    payload = {
        "message": query,
        "customer_id": customer_id,
        "tenant_id": tenant_id
    }
    try:
        response = requests.post(API_URL, json=payload, timeout=120)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def contains_any(text: str, phrases: list) -> list:
    text_lower = text.lower()
    return [p for p in phrases if p.lower() in text_lower]

def evaluate_case(case: dict) -> dict:
    query = case["query"]
    expected = case["expected"]
    result = call_api(query)

    response_text = result.get("response", "") or ""
    blocked = result.get("blocked", False)
    escalated = result.get("escalated", False)

    checks = {}
    passed = True

    # 1. Block check
    if expected["should_block"] != blocked:
        checks["block"] = f"FAIL (expected {expected['should_block']}, got {blocked})"
        passed = False
    else:
        checks["block"] = "PASS"

    # 2. Escalation check
    if expected["should_escalate"] != escalated:
        checks["escalate"] = f"FAIL (expected {expected['should_escalate']}, got {escalated})"
        passed = False
    else:
        checks["escalate"] = "PASS"

    # 3. Ask for photos
    if expected.get("should_ask_for_photos"):
        photo_keywords = ["photo", "photos", "image", "images", "picture", "pictures"]
        if any(k in response_text.lower() for k in photo_keywords):
            checks["ask_for_photos"] = "PASS"
        else:
            checks["ask_for_photos"] = "FAIL (did not ask for photos)"
            passed = False
    else:
        checks["ask_for_photos"] = "SKIP"

    # 4. Forbidden phrases
    forbidden = expected.get("must_not_contain", [])
    found = contains_any(response_text, forbidden)
    if found:
        checks["hallucination"] = f"FAIL (found: {found})"
        passed = False
    else:
        checks["hallucination"] = "PASS"

    return {
        "id": case["id"],
        "query": query,
        "passed": passed,
        "checks": checks,
        "blocked": blocked,
        "escalated": escalated,
        "response_preview": response_text[:200]
    }

def main():
    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        golden_set = json.load(f)

    print(f"\nRunning evaluation on {len(golden_set)} cases...\n")
    results = []
    passed_count = 0

    for case in golden_set:
        print(f"Testing: {case['id']} ...", end=" ")
        result = evaluate_case(case)
        results.append(result)

        if result["passed"]:
            print("PASS")
            passed_count += 1
        else:
            print("FAIL")
            for k, v in result["checks"].items():
                if "FAIL" in v:
                    print(f"   - {k}: {v}")

        time.sleep(1)  # small delay between requests

    # Summary
    total = len(results)
    print("\n" + "="*50)
    print(f"EVALUATION SUMMARY: {passed_count}/{total} passed")
    print("="*50)

    # Save report
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"eval_report_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total": total,
                "passed": passed_count,
                "failed": total - passed_count,
                "pass_rate": round(passed_count / total * 100, 1)
            },
            "results": results
        }, f, indent=2)

    print(f"\nReport saved to: {report_path}")

if __name__ == "__main__":
    main()