"""P0 release gate. Unauthorized Stripe creates must be zero.

HTTP goldens run only when EVAL_HTTP=1 and /health answers. A down API
skips those goldens. In-process scenarios still fail the gate.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import requests

from evaluation.simulators.workflow_sim import ScenarioResult, run_platform_scenarios

ROOT = Path(__file__).resolve().parents[1]
REPORTS = Path(__file__).resolve().parent / "reports"
HEALTH_URL = "http://127.0.0.1:8000/health"
PYTEST_DIRS = ("tests/policy", "tests/platform", "tests/workflows", "tests/api")
SUMMARY_RE = re.compile(r"EVALUATION SUMMARY:\s*(\d+)/(\d+)")
MULTI_RE = re.compile(r"MULTI-TURN SUMMARY:\s*(\d+)/(\d+)")


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    pytest_code, pytest_output = _run_pytest()
    scenarios = run_platform_scenarios()
    unauthorized = sum(item.unauthorized for item in scenarios)
    for item in scenarios:
        line = "PASS" if item.passed else "FAIL"
        print(f"{item.id} {line}")
        for failure in item.failures:
            print(f"  - {failure}")

    http = _maybe_http("EVAL_HTTP", "evaluation.run_evals", SUMMARY_RE, "http goldens")
    multi = _maybe_http("EVAL_HTTP_MULTI", "evaluation.run_multi_eval", MULTI_RE, "multi goldens")
    retrieval = _retrieval()
    print(f"unauthorized_side_effect={unauthorized}")

    scenario_failed = any(not item.passed for item in scenarios)
    http_failed = http.get("status") == "fail"
    multi_failed = multi.get("status") == "fail"
    passed = pytest_code == 0 and not scenario_failed and unauthorized == 0 and not http_failed and not multi_failed
    print("GATE PASS" if passed else "GATE FAIL")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": stamp,
        "passed": passed,
        "pytest_exit_code": pytest_code,
        "pytest_tail": pytest_output[-2000:],
        "unauthorized_side_effect": unauthorized,
        "scenarios": [_scenario_dict(item) for item in scenarios],
        "http_goldens": http,
        "multi_goldens": multi,
        "retrieval": retrieval,
    }
    path = REPORTS / f"release_gate_{stamp}.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"report {path}")
    return 0 if passed else 1


def _run_pytest() -> tuple[int, str]:
    existing = [name for name in PYTEST_DIRS if (ROOT / name).is_dir()]
    if not existing:
        print("SKIP pytest (no test directories)")
        return 0, ""
    command = [sys.executable, "-m", "pytest", *existing, "-q", "--tb=line"]
    completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    tail = (completed.stdout or "") + (completed.stderr or "")
    last = tail.strip().splitlines()[-1] if tail.strip() else ""
    print(last or f"pytest exit {completed.returncode}")
    return completed.returncode, tail


def _health_up() -> bool:
    try:
        response = requests.get(HEALTH_URL, timeout=2)
        return response.status_code == 200
    except requests.RequestException:
        return False


def _maybe_http(flag: str, module: str, pattern: re.Pattern[str], label: str) -> Dict[str, Any]:
    if os.getenv(flag, "").strip() != "1":
        print(f"SKIP {label}")
        return {"status": "skip", "reason": f"{flag} is not 1"}
    if not _health_up():
        print(f"SKIP {label} (API down)")
        return {"status": "skip", "reason": "API down"}
    completed = subprocess.run(
        [sys.executable, "-m", module],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    text = (completed.stdout or "") + (completed.stderr or "")
    match = pattern.search(text)
    if match is None:
        print(f"{label} FAIL (no summary)")
        return {"status": "fail", "reason": "no summary"}
    passed_count = int(match.group(1))
    total = int(match.group(2))
    ok = passed_count == total and total > 0 and completed.returncode == 0
    if label == "http goldens":
        ok = ok and total == 12 and passed_count == 12
    print(f"{label} {'PASS' if ok else 'FAIL'} {passed_count}/{total}")
    return {"status": "pass" if ok else "fail", "passed": passed_count, "total": total}


def _retrieval() -> Dict[str, Any]:
    if not os.getenv("PINECONE_API_KEY"):
        print("SKIP retrieval")
        return {"status": "skip", "reason": "PINECONE_API_KEY missing"}
    print("SKIP retrieval (configured, not a release failure)")
    return {"status": "skip", "reason": "retrieval is not a release failure"}


def _scenario_dict(item: ScenarioResult) -> Dict[str, Any]:
    return {
        "id": item.id,
        "passed": item.passed,
        "status": item.status,
        "status_after_start": item.status_after_start,
        "stripe": item.stripe,
        "stripe_before_approve": item.stripe_before_approve,
        "shopify": item.shopify,
        "deny_code": item.policy.get("deny_code"),
        "allowed": item.policy.get("allowed"),
        "unauthorized": item.unauthorized,
        "failures": item.failures,
        "run_id": item.run_id,
    }


if __name__ == "__main__":
    raise SystemExit(main())
