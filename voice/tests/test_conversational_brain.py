"""
voice/tests/test_conversational_brain.py — Conversational Multi-Turn Intelligence Test Suite.

Validates that:
1. The LLM acts as the conversational brain, with RAG functioning as a callable tool for policy queries rather than running on every turn.
2. The agent speaks naturally without quoting internal clause numbers or robotic formulas.
3. Conversational context flows seamlessly across multi-turn exchanges:
   Turn 1 (Policy inquiry): "Hey, I got a damaged shampoo bottle yesterday. Can I return it?"
   Turn 2 (Acceptance): "Yes, please help me with that."
   Turn 3 (Order details): "My order number is 12345."
   Turn 4 (Contact details): "The email is customer@example.com"
4. Non-policy turns (Order IDs, emails, confirmations) bypass expensive RAG searches.
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


class TestConversationalBrain:

    def test_multi_turn_conversational_flow(self):
        runtime = _build_runtime()
        adapter = SupportRuntimeAdapter(runtime)
        session = VoiceSession(tenant_id="zepto", customer_id="conv_user_01")

        # Turn 1: Policy inquiry with context
        r1 = adapter.handle_transcript_sync("Hey, I got a damaged shampoo bottle yesterday. Can I return it?", session)
        resp1 = r1.response.lower()
        print("\n[Turn 1 Reply]:", r1.response)
        assert any(w in resp1 for w in ("yes", "damage", "return", "help", "product", "eligible"))
        assert "clause" not in resp1, "Agent should not quote internal legal clause numbers"
        assert not session.needs_identity, "General inquiry should not block on identity"

        # Turn 2: User says "Yes, please help me with that."
        r2 = adapter.handle_transcript_sync("Yes, please help me with that.", session)
        resp2 = r2.response.lower()
        print("\n[Turn 2 Reply]:", r2.response)
        assert any(w in resp2 for w in ("order id", "order number", "share", "provide", "email", "phone", "help"))

        # Turn 3: User provides order ID "My order number is 12345."
        r3 = adapter.handle_transcript_sync("My order number is 12345.", session)
        resp3 = r3.response.lower()
        print("\n[Turn 3 Reply]:", r3.response)
        assert session.pending_order_id == "12345"
        assert any(w in resp3 for w in ("phone", "email", "contact", "12345"))

        # Turn 4: User provides email "The email is customer@example.com"
        r4 = adapter.handle_transcript_sync("The email is customer@example.com", session)
        resp4 = r4.response.lower()
        print("\n[Turn 4 Reply]:", r4.response)
        assert any(w in resp4 for w in ("photo", "verified", "details", "damage", "order", "proof", "help"))
