"""
voice/tests/test_policy_vs_action_suite.py — Policy vs. Action Separation Test Suite.

Validates that the voice agent uses the exact same SupportRuntime/LangGraph brain,
correctly routing policy/informational questions to RAG + QA, and action requests
to the Identity Gate and Order Workflow tools.

Test Matrix:
1. "Hi"                                        -> Greeting
2. "What's your return policy?"                -> RAG answer (no identity challenge)
3. "What's your refund policy?"                -> RAG answer (no identity challenge)
4. "What's the policy for damaged products?"   -> RAG answer (no identity challenge)
5. "Can I return a defective product?"         -> RAG answer (no identity challenge)
6. "How long do I have to return something?"   -> RAG answer (no identity challenge)
7. "I want to return my order."                -> Ask identity challenge
8. "I want a refund."                          -> Ask identity challenge
9. "Where is my order?"                        -> Ask identity challenge
10. "Cancel my order."                         -> Ask identity challenge
11. "My order is damaged, I want to return it."-> Ask identity challenge
12. "What are your delivery policies?"         -> RAG answer (no identity challenge)
"""
from __future__ import annotations

import pytest
from dotenv import load_dotenv

load_dotenv(override=True)

from tools.bootstrap import register_default_tools
register_default_tools()

from config.loaders import load_tenant_config
from interactions.service import InteractionService
from memory.service import MemoryService
from observability.logging import log_event, new_request_id
from orchestration.graph import compiled_graph
from runtime.support_runtime import SupportRuntime
from voice.adapter import SupportRuntimeAdapter
from voice.context import VoiceSession


def _invoke_graph(inputs: dict) -> dict:
    return compiled_graph.invoke(inputs)


def _build_runtime() -> SupportRuntime:
    def _load_tenant(tenant_id: str):
        cfg = load_tenant_config(tenant_id)
        return cfg.dict() if hasattr(cfg, "dict") else (
            cfg.model_dump() if hasattr(cfg, "model_dump") else cfg
        )

    return SupportRuntime(
        graph_invoker=_invoke_graph,
        memory_service=MemoryService(),
        interaction_service=InteractionService(),
        load_tenant_config=_load_tenant,
        new_request_id=new_request_id,
        log_event=log_event,
        apply_output_guard=lambda text: text or "",
    )


@pytest.fixture(scope="module")
def voice_adapter():
    runtime = _build_runtime()
    return SupportRuntimeAdapter(runtime)


class TestPolicyVsActionRouting:

    # 1. Greeting
    def test_01_greeting(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_01")
        result = voice_adapter.handle_transcript_sync("Hi", session)
        assert result.response is not None
        assert any(w in result.response.lower() for w in ("help", "hi", "zepto", "hello"))
        assert not session.needs_identity

    # 2. Return Policy (RAG)
    def test_02_return_policy_rag(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_02")
        result = voice_adapter.handle_transcript_sync("What's your return policy?", session)
        resp = result.response.lower()
        assert not session.needs_identity, "Policy query should not require identity"
        assert "return" in resp or "policy" in resp or "days" in resp or "product" in resp
        assert "please provide your order id" not in resp

    # 3. Refund Policy (RAG)
    def test_03_refund_policy_rag(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_03")
        result = voice_adapter.handle_transcript_sync("What's your refund policy?", session)
        resp = result.response.lower()
        assert not session.needs_identity, "Policy query should not require identity"
        assert "refund" in resp or "policy" in resp or "credit" in resp or "account" in resp or "return" in resp
        assert "please provide your order id" not in resp

    # 4. Damaged Products Policy (RAG)
    def test_04_damaged_policy_rag(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_04")
        result = voice_adapter.handle_transcript_sync("What's the policy for damaged products?", session)
        resp = result.response.lower()
        assert not session.needs_identity, "Policy query should not require identity"
        assert "damage" in resp or "quality" in resp or "return" in resp or "proof" in resp
        assert "please provide your order id" not in resp

    # 5. Defective Product (RAG)
    def test_05_defective_product_rag(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_05")
        result = voice_adapter.handle_transcript_sync("Can I return a defective product?", session)
        resp = result.response.lower()
        assert not session.needs_identity, "Policy query should not require identity"
        assert "yes" in resp or "return" in resp or "damaged" in resp or "defective" in resp or "deteriorated" in resp
        assert "please provide your order id" not in resp

    # 6. Return Window / Duration (RAG)
    def test_06_return_window_rag(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_06")
        result = voice_adapter.handle_transcript_sync("How long do I have to return something?", session)
        resp = result.response.lower()
        assert not session.needs_identity, "Policy query should not require identity"
        assert "time" in resp or "delivery" in resp or "return" in resp or "hour" in resp or "day" in resp or "check" in resp
        assert "please provide your order id" not in resp

    # 7. Action Request: Return Order -> Ask Identity
    def test_07_action_return_order_identity(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_07")
        result = voice_adapter.handle_transcript_sync("I want to return my order.", session)
        resp = result.response.lower()
        assert session.needs_identity, "Action request must require identity"
        assert any(w in resp for w in ("order id", "order number", "email", "phone", "verify"))

    # 8. Action Request: Refund -> Ask Identity
    def test_08_action_refund_identity(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_08")
        result = voice_adapter.handle_transcript_sync("I want a refund.", session)
        resp = result.response.lower()
        assert session.needs_identity, "Action request must require identity"
        assert any(w in resp for w in ("order id", "order number", "email", "phone", "verify"))

    # 9. Action Request: Where is my order -> Ask Identity
    def test_09_action_where_is_my_order_identity(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_09")
        result = voice_adapter.handle_transcript_sync("Where is my order?", session)
        resp = result.response.lower()
        assert session.needs_identity, "Action request must require identity"
        assert any(w in resp for w in ("order id", "order number", "email", "phone", "verify"))

    # 10. Action Request: Cancel my order -> Ask Identity
    def test_10_action_cancel_order_identity(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_10")
        result = voice_adapter.handle_transcript_sync("Cancel my order.", session)
        resp = result.response.lower()
        assert session.needs_identity, "Action request must require identity"
        assert any(w in resp for w in ("order id", "order number", "email", "phone", "verify"))

    # 11. Action Request: Damaged order return -> Ask Identity
    def test_11_action_damaged_return_identity(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_11")
        result = voice_adapter.handle_transcript_sync("My order is damaged, I want to return it.", session)
        resp = result.response.lower()
        assert session.needs_identity, "Action request must require identity"
        assert any(w in resp for w in ("order id", "order number", "email", "phone", "verify"))

    # 12. Delivery Policy (RAG)
    def test_12_delivery_policy_rag(self, voice_adapter):
        session = VoiceSession(tenant_id="zepto", customer_id="test_user_12")
        result = voice_adapter.handle_transcript_sync("What are your delivery policies?", session)
        resp = result.response.lower()
        assert not session.needs_identity, "Policy query should not require identity"
        assert "deliver" in resp or "time" in resp or "address" in resp or "order" in resp or "policy" in resp
        assert "please provide your order id" not in resp
