import json
import time
import requests
from pathlib import Path
from datetime import datetime

API_URL = "http://127.0.0.1:8000/chat"
GOLDEN_SET_PATH = Path(__file__).parent / "golden_set_multiturn.json"
REPORTS_DIR = Path(__file__).parent / "reports"
REPORTS_DIR.mkdir(exist_ok=True)


def call_api(message: str, customer_id: str, tenant_id: str = "zepto", session_id: str | None = None):
    payload = {
        "message": message,
        "customer_id": customer_id,
        "tenant_id": tenant_id
    }
    if session_id:
        payload["session_id"] = session_id

    response = requests.post(API_URL, json=payload, timeout=120)
    response.raise_for_status()
    return response.json()


def contains_any(text: str, phrases: list[str]) -> list[str]:
    text_l = (text or "").lower()
    return [p for p in phrases if p.lower() in text_l]


def evaluate_turn(result: dict, expected: dict) -> tuple[bool, dict]:
    response_text = result.get("response", "") or ""
    blocked = result.get("blocked", False)
    escalated = result.get("escalated", False)

    checks = {}
    passed = True

    if expected["should_block"] != blocked:
        checks["block"] = f"FAIL (expected {expected['should_block']}, got {blocked})"
        passed = False
    else:
        checks["block"] = "PASS"

    if expected["should_escalate"] != escalated:
        checks["escalate"] = f"FAIL (expected {expected['should_escalate']}, got {escalated})"
        passed = False
    else:
        checks["escalate"] = "PASS"

    if expected.get("should_ask_for_photos"):
        photo_keywords = ["photo", "photos", "image", "images", "picture", "pictures"]
        if any(k in response_text.lower() for k in photo_keywords):
            checks["ask_for_photos"] = "PASS"
        else:
            checks["ask_for_photos"] = "FAIL (did not ask for photos)"
            passed = False
    else:
        checks["ask_for_photos"] = "SKIP"

    forbidden = expected.get("must_not_contain", [])
    found = contains_any(response_text, forbidden)
    if found:
        checks["hallucination_or_regression"] = f"FAIL (found: {found})"
        passed = False
    else:
        checks["hallucination_or_regression"] = "PASS"

    return passed, checks


def main():
    with open(GOLDEN_SET_PATH, "r", encoding="utf-8") as f:
        golden_set = json.load(f)

    print(f"\nRunning multi-turn evaluation on {len(golden_set)} scenarios...\n")
    results = []
    passed_scenarios = 0

    for scenario in golden_set:
        scenario_id = scenario["id"]
        customer_id = f"eval_{scenario_id}"
        session_id = None
        scenario_passed = True
        turn_results = []

        print(f"Scenario: {scenario_id}")

        for idx, turn in enumerate(scenario["turns"], start=1):
            print(f"  Turn {idx}: {turn['message'][:60]}...")
            result = call_api(
                message=turn["message"],
                customer_id=customer_id,
                session_id=session_id
            )

            # persist session for next turn
            session_id = result.get("session_id") or session_id

            passed, checks = evaluate_turn(result, turn["expected"])
            if not passed:
                scenario_passed = False

            turn_results.append({
                "turn": idx,
                "message": turn["message"],
                "passed": passed,
                "checks": checks,
                "session_id": session_id,
                "case_id": result.get("case_id"),
                "escalated": result.get("escalated", False),
                "blocked": result.get("blocked", False),
                "response_preview": (result.get("response") or "")[:220]
            })

            status = "PASS" if passed else "FAIL"
            print(f"    -> {status}")
            if not passed:
                for k, v in checks.items():
                    if "FAIL" in v:
                        print(f"       - {k}: {v}")

            time.sleep(1)

        if scenario_passed:
            passed_scenarios += 1
            print("  Scenario result: PASS\n")
        else:
            print("  Scenario result: FAIL\n")

        results.append({
            "id": scenario_id,
            "passed": scenario_passed,
            "turns": turn_results
        })

    total = len(results)
    print("=" * 50)
    print(f"MULTI-TURN SUMMARY: {passed_scenarios}/{total} scenarios passed")
    print("=" * 50)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = REPORTS_DIR / f"multiturn_eval_report_{timestamp}.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump({
            "summary": {
                "total": total,
                "passed": passed_scenarios,
                "failed": total - passed_scenarios,
                "pass_rate": round(passed_scenarios / total * 100, 1) if total else 0
            },
            "results": results
        }, f, indent=2)

    print(f"\nReport saved to: {report_path}")


if __name__ == "__main__":
    main()