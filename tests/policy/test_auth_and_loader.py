"""Loader, auth ladder, and the public import surface. No server and no keys."""
import ast
from pathlib import Path

from config.tenant_contract import load_policy_yaml
from policy import PolicyDecision, evaluate
from policy.loader import clear_policy_cache, should_flag_escalation

_POLICY_ROOT = Path(__file__).resolve().parents[2] / "policy"
_FORBIDDEN = ("fastapi", "pinecone", "shopify", "stripe", "orchestration", "langchain")


def test_refund_decision_uses_the_yaml_id_and_version():
    document = load_policy_yaml("zepto", "refund")
    decision = evaluate(
        "zepto",
        "Refund",
        auth_level="verified",
        slots={"amount": 500, "reason": "damaged", "photos_received": True},
    )
    assert isinstance(decision, PolicyDecision)
    assert decision.policy_id == document["id"]
    assert decision.policy_version == str(document["version"])
    assert decision.policy_version == "2026.09.0"


def test_refund_cap_comes_from_the_policy_file_not_a_hardcoded_branch():
    document = load_policy_yaml("zepto", "refund")
    auto_max = float(document["thresholds"]["auto_refund_max"])
    clear_policy_cache()
    under = evaluate(
        "zepto",
        "refund",
        auth_level="verified",
        slots={"amount": auto_max, "reason": "late", "photos_received": False},
    )
    over = evaluate(
        "zepto",
        "refund",
        auth_level="verified",
        slots={"amount": auto_max + 1, "reason": "late", "photos_received": False},
    )
    assert under.allowed is True
    assert over.allowed is False
    assert over.requires_approval is True
    assert over.max_amount == float(document["thresholds"]["manager_refund_max"])


def test_unknown_tenant_returns_a_decision():
    decision = evaluate(
        "no-such-brand",
        "refund",
        auth_level="verified",
        slots={"amount": 500, "reason": "late", "photos_received": False},
    )
    assert isinstance(decision, PolicyDecision)
    assert decision.policy_id == "refund"
    assert decision.allowed is True
    assert decision.policy_version == "unversioned"


def test_unknown_action_is_out_of_policy():
    decision = evaluate("zepto", "chargeback", auth_level="verified", slots={"amount": 10})
    assert decision.allowed is False
    assert decision.deny_code == "OUT_OF_POLICY"
    assert decision.reasons == ["unknown_action"]
    assert decision.requires_approval is False
    assert decision.requires_strong_auth is False


def test_policy_question_is_allowed_for_anonymous():
    decision = evaluate("zepto", "policy", auth_level="anonymous", slots={})
    assert decision.allowed is True
    assert decision.requires_approval is False
    assert decision.requires_strong_auth is False
    assert decision.requires_inputs == []
    assert "knowledge_ok" in decision.reasons
    assert decision.deny_code is None


def test_order_status_stays_allowed_but_flags_tool_auth():
    anonymous = evaluate("zepto", "order_status", auth_level="anonymous", slots={"order_id": "12345"})
    assert anonymous.allowed is True
    assert anonymous.requires_strong_auth is True
    assert anonymous.deny_code is None
    assert "tool_requires_auth" in anonymous.reasons

    identified = evaluate("zepto", "order_status", auth_level="identified", slots={"order_id": "12345"})
    assert identified.allowed is True
    assert identified.requires_strong_auth is False
    assert "auth_ok" in identified.reasons
    assert "tool_requires_auth" not in identified.reasons


def test_escalation_file_is_loaded_but_not_applied_by_evaluate():
    assert should_flag_escalation("zepto", ["fraud"]) is True
    assert should_flag_escalation("zepto", ["amount_within_auto"]) is False
    decision = evaluate(
        "zepto",
        "refund",
        auth_level="verified",
        slots={"amount": 2500, "reason": "late", "photos_received": False},
    )
    assert decision.requires_approval is True
    assert "fraud" not in decision.reasons


def test_policy_package_does_not_import_runtime_stacks():
    offenders = []
    for path in _POLICY_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            for name in names:
                if name in _FORBIDDEN:
                    offenders.append(f"{path.name}: {name}")
    assert offenders == []
