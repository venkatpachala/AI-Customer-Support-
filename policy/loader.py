"""Merge tenant.yaml with policies/*.yaml into one resolved pack per tenant.

Policy YAML wins when a key is present. A missing key falls back to the
platform tenant limits and auth ladder. A missing tenant file uses the
default contract from load_platform_tenant and does not raise.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence, Tuple

from config.tenant_contract import load_platform_tenant, load_policy_yaml
from policy.rules import normalize_token

_MONEY_ACTIONS = {"refund"}
_PHOTO_ACTIONS = {"refund", "return", "replacement"}
_PREFERENCE_ACTIONS = {"refund", "return", "replacement"}
_DEFAULT_BLOCKED_CANCEL = ("delivered", "fulfilled")
_DEFAULT_OUT_OF_POLICY = ("preference",)

_PACKS: Dict[str, "ResolvedPolicyPack"] = {}


@dataclass(frozen=True)
class ActionPolicy:
    action: str
    policy_id: str
    policy_version: str
    min_auth: str
    auto_max: Optional[float]
    manager_max: Optional[float]
    photo_required_for: Tuple[str, ...]
    out_of_policy_reasons: Tuple[str, ...]
    blocked_order_statuses: Tuple[str, ...]


@dataclass(frozen=True)
class ResolvedPolicyPack:
    tenant_id: str
    policy_pack_version: str
    actions: Dict[str, ActionPolicy]
    escalate_on: Tuple[str, ...]

    def action(self, name: str) -> ActionPolicy:
        return self.actions[name]


def clear_policy_cache() -> None:
    """Drop the in-process pack cache. Tests and a config reload call this."""
    _PACKS.clear()


def load_resolved_pack(tenant_id: str) -> ResolvedPolicyPack:
    key = (tenant_id or "").strip()
    cached = _PACKS.get(key)
    if cached is not None:
        return cached
    pack = _build_pack(key)
    _PACKS[key] = pack
    return pack


def should_flag_escalation(tenant_id: str, reason_codes: Sequence[str]) -> bool:
    """True when any code is listed on the tenant escalation policy.

    The engine does not escalate by itself. A later HITL step can call this.
    """
    pack = load_resolved_pack(tenant_id)
    wanted = {normalize_token(code) for code in reason_codes if normalize_token(code)}
    flagged = {normalize_token(code) for code in pack.escalate_on}
    return bool(wanted & flagged)


def _build_pack(tenant_id: str) -> ResolvedPolicyPack:
    tenant = load_platform_tenant(tenant_id)
    documents = {
        "refund": load_policy_yaml(tenant_id, "refund"),
        "return": load_policy_yaml(tenant_id, "return"),
        "cancel": load_policy_yaml(tenant_id, "cancel"),
        "replacement": load_policy_yaml(tenant_id, "replacement"),
        "escalation": load_policy_yaml(tenant_id, "escalation"),
    }
    # Replacement with no file of its own follows the return pack.
    if not documents["replacement"]:
        documents["replacement"] = dict(documents["return"])

    version = tenant.versions.policy_pack or "unversioned"
    actions = {
        name: _resolve_action(
            name,
            documents.get(name) or {},
            tenant_min_auth=_tenant_min_auth(tenant, name),
            auto_max=float(tenant.limits.auto_refund_max),
            manager_max=float(tenant.limits.manager_refund_max),
            photo_required_for=tuple(tenant.limits.photo_required_for or []),
            pack_version=version,
        )
        for name in ("refund", "return", "cancel", "replacement", "order_status", "policy")
    }
    return ResolvedPolicyPack(
        tenant_id=tenant.id,
        policy_pack_version=version,
        actions=actions,
        escalate_on=_escalation_codes(documents["escalation"]),
    )


def _tenant_min_auth(tenant: Any, action: str) -> str:
    intents = tenant.auth.intents or {}
    declared = intents.get(action)
    if declared:
        return str(declared)
    defaults = {
        "refund": "verified",
        "return": "identified",
        "cancel": "identified",
        "replacement": "identified",
        "order_status": "identified",
        "policy": "anonymous",
    }
    return defaults.get(action, "verified")


def _resolve_action(
    action: str,
    document: Dict[str, Any],
    *,
    tenant_min_auth: str,
    auto_max: float,
    manager_max: float,
    photo_required_for: Tuple[str, ...],
    pack_version: str,
) -> ActionPolicy:
    thresholds = _mapping(document.get("thresholds"))
    min_auth = _auth_min(document, tenant_min_auth)
    resolved_auto = auto_max
    resolved_manager = manager_max
    if action in _MONEY_ACTIONS:
        resolved_auto = _first_number(
            document,
            thresholds,
            ("auto_max", "auto_refund_max"),
            auto_max,
        )
        resolved_manager = _first_number(
            document,
            thresholds,
            ("manager_max", "manager_refund_max"),
            manager_max,
        )

    photos: Tuple[str, ...] = ()
    if action in _PHOTO_ACTIONS:
        photos = _first_tokens(
            document,
            thresholds,
            ("photo_required_for", "require_photos_if"),
            photo_required_for,
        )

    out_of_policy: Tuple[str, ...] = ()
    if action in _PREFERENCE_ACTIONS:
        out_of_policy = _first_tokens(
            document,
            thresholds,
            ("out_of_policy_reasons",),
            _DEFAULT_OUT_OF_POLICY,
        )

    blocked: Tuple[str, ...] = ()
    if action == "cancel":
        blocked = _first_tokens(
            document,
            thresholds,
            ("blocked_order_statuses",),
            _DEFAULT_BLOCKED_CANCEL,
        )

    policy_id = str(document.get("id") or action).strip() or action
    policy_version = str(document.get("version") or pack_version).strip() or pack_version
    return ActionPolicy(
        action=action,
        policy_id=policy_id,
        policy_version=policy_version,
        min_auth=normalize_token(min_auth) or tenant_min_auth,
        auto_max=resolved_auto if action in _MONEY_ACTIONS else None,
        manager_max=resolved_manager if action in _MONEY_ACTIONS else None,
        photo_required_for=photos,
        out_of_policy_reasons=out_of_policy,
        blocked_order_statuses=blocked,
    )


def _auth_min(document: Dict[str, Any], fallback: str) -> str:
    """Policy auth.min_level wins, then requires_auth, then the tenant ladder."""
    auth = document.get("auth")
    if isinstance(auth, dict) and auth.get("min_level"):
        return str(auth["min_level"])
    if isinstance(auth, str) and auth.strip():
        return auth
    if document.get("min_level"):
        return str(document["min_level"])
    if document.get("requires_auth"):
        return str(document["requires_auth"])
    return fallback


def _first_number(
    document: Dict[str, Any],
    thresholds: Dict[str, Any],
    keys: Sequence[str],
    fallback: float,
) -> float:
    for source in (document, thresholds):
        for key in keys:
            if key in source and source[key] is not None:
                try:
                    return float(source[key])
                except (TypeError, ValueError):
                    continue
    return float(fallback)


def _first_tokens(
    document: Dict[str, Any],
    thresholds: Dict[str, Any],
    keys: Sequence[str],
    fallback: Tuple[str, ...],
) -> Tuple[str, ...]:
    for source in (document, thresholds):
        for key in keys:
            if key not in source:
                continue
            return _as_tokens(source.get(key))
    return tuple(normalize_token(item) for item in fallback if normalize_token(item))


def _as_tokens(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        token = normalize_token(value)
        return (token,) if token else ()
    if isinstance(value, (list, tuple)):
        tokens = []
        for item in value:
            token = normalize_token(item)
            if token and token not in tokens:
                tokens.append(token)
        return tuple(tokens)
    return ()


def _escalation_codes(document: Dict[str, Any]) -> Tuple[str, ...]:
    thresholds = _mapping(document.get("thresholds"))
    found = []
    for source in (document, thresholds):
        for key in ("escalate_on", "escalate_when"):
            if key not in source:
                continue
            for token in _as_tokens(source.get(key)):
                if token not in found:
                    found.append(token)
    return tuple(found)


def _mapping(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}
