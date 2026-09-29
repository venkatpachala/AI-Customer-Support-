"""
voice/adapter.py — Phase 3 Voice Adapter.

Bridges VoiceSession ↔ SupportRuntime.

Phase 3 additions:
- Passes full conversation memory (active_intent, conversation_turns, pending_action,
  last_tool_result, photos_requested/received) into memory_context each turn.
- Emits a "thinking phrase" to TTS when a tool-requiring turn is detected (>1s expected).
- Records per-turn VoiceTurnTrace for structured observability.
- Writes back updated conversation state after each turn (active_intent, last_tool_result, etc.)
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from runtime.context import RequestContext, AuthContext
from runtime.response import RuntimeResponse
from voice.context import VoiceSession
from voice.turn_trace import VoiceTurnTrace


class SupportRuntimeAdapter:
    def __init__(self, runtime: Any, on_thinking_phrase: Optional[Callable[[str], None]] = None):
        """
        Args:
            runtime: SupportRuntime instance
            on_thinking_phrase: Optional callback called with the thinking phrase string
                                before the runtime is invoked. Voice pipeline uses this
                                to immediately push a TextFrame to TTS.
        """
        self.runtime = runtime
        self.on_thinking_phrase = on_thinking_phrase

    # ── Greeting detection ────────────────────────────────────────────────────

    def _is_greeting(self, text: str) -> bool:
        t = (text or "").strip().lower()
        return t in {
            "hi", "hello", "hey", "hi!", "hello!", "hey!",
            "good morning", "good afternoon", "good evening",
        }

    def _greeting_response(self, session: VoiceSession) -> RuntimeResponse:
        return RuntimeResponse(
            response="Hi! I'm here to help with orders, returns, refunds, or any policy questions.",
            confidence=1.0,
            session_id=session.session_id,
            case_id=session.case_id,
            auth_level=session.auth_level,
            intent="greeting",
        )

    # ── Memory context builder ────────────────────────────────────────────────

    def _build_memory_context(self, session: VoiceSession) -> Dict[str, Any]:
        """Build the full memory_context dict to inject into each SupportRuntime call."""
        return {
            # Auth state
            "auth_level": session.auth_level,
            "verified": session.verified,
            "verified_customer": session.verified_customer,
            "verified_order_ids": list(session.verified_order_ids or []),

            # Identity in progress
            "pending_order_id": session.pending_order_id,
            "pending_contact": session.pending_contact,
            "customer_contact": session.customer_contact,
            "active_order_id": session.pending_order_id,
            "needs_identity": session.needs_identity,

            # Issue / action type
            "issue_type": session.issue_type,
            "intent": session.issue_type,

            # ── Phase 3: conversation memory ──────────────────────────────────
            "active_intent": session.active_intent,
            "active_case_type": session.active_case_type,
            "pending_action": session.pending_action,
            "last_tool_name": session.last_tool_name,
            "last_tool_result": session.last_tool_result,
            "conversation_turns": list(session.conversation_turns[-6:]),  # last 6 turns
            "photos_requested": session.photos_requested,
            "photos_received": session.photos_received,
            "detected_language": session.detected_language,
        }

    # ── RequestContext builder ────────────────────────────────────────────────

    def _build_context(self, text: str, session: VoiceSession) -> RequestContext:
        session.normalize_auth()
        return RequestContext(
            message=text,
            tenant_id=session.tenant_id,
            customer_id=session.customer_id,
            session_id=session.session_id,
            case_id=session.case_id,
            channel="voice",
            language=session.language,
            memory_context=self._build_memory_context(session),
            auth=AuthContext(
                auth_level=session.auth_level,
                verified=session.verified,
                verified_customer=session.verified_customer,
                verified_order_ids=list(session.verified_order_ids or []),
                contact=session.customer_contact or session.pending_contact,
            ),
        )

    # ── Session writeback ─────────────────────────────────────────────────────

    def _write_back_session(self, session: VoiceSession, result: RuntimeResponse, user_text: str) -> None:
        raw = result.raw or {}

        # Session / case IDs
        if result.session_id:
            session.session_id = result.session_id
        if result.case_id:
            session.case_id = result.case_id

        # Auth ladder
        if result.auth_level:
            session.auth_level = str(result.auth_level).lower().strip()
        if "verified" in raw:
            session.verified = bool(raw.get("verified"))
        if "verified_customer" in raw:
            session.verified_customer = bool(raw.get("verified_customer"))
        session.normalize_auth()

        # Orders
        from identity.service import extract_order_id, extract_contact
        oid = (result.order_id
               or raw.get("resolved_order_id")
               or raw.get("order_id")
               or raw.get("pending_order_id"))
        if not oid:
            oid = extract_order_id(raw.get("message") or "")
        if oid:
            session.pending_order_id = str(oid)
            if session.auth_level in ("identified", "verified"):
                if str(oid) not in session.verified_order_ids:
                    session.verified_order_ids.append(str(oid))

        # Contact
        contact = raw.get("customer_contact") or raw.get("pending_contact")
        if not contact:
            contact = extract_contact(raw.get("message") or "")
        if contact:
            session.pending_contact = str(contact)
            if session.auth_level in ("identified", "verified"):
                session.customer_contact = str(contact)

        # Needs identity
        session.needs_identity = bool(
            getattr(result, "needs_identity", None)
            if getattr(result, "needs_identity", None) is not None
            else raw.get("needs_identity", session.needs_identity)
        )

        # Sticky issue type
        intent = (result.intent or raw.get("intent") or "").lower().strip()
        if intent and intent not in ("greeting", "general", "policy", "faq", "policy_query", "conversational"):
            session.issue_type = intent

        # ── Phase 3: conversation memory writeback ────────────────────────────

        # Carry forward active_intent from supervisor output (via result.raw)
        new_active_intent = raw.get("active_intent") or result.intent
        if new_active_intent and new_active_intent not in (
            "general", "greeting", "policy_query", "faq", "conversational", "knowledge"
        ):
            session.active_intent = new_active_intent
        elif result.intent in ("general", "greeting", "conversational"):
            # Greeting/smalltalk doesn't reset active_intent — preserve for continuity
            pass

        # Active case type
        new_case_type = raw.get("active_case_type")
        if new_case_type:
            session.active_case_type = new_case_type
        elif session.active_intent in ("return", "damaged_return") and not session.active_case_type:
            session.active_case_type = session.active_intent

        # Pending action
        pending = raw.get("pending_action")
        if pending:
            session.pending_action = pending

        # Tool result memory
        tool_results = result.tool_results or {}
        if tool_results:
            for tool_name, tool_result in tool_results.items():
                session.last_tool_name = tool_name
                session.last_tool_result = tool_result if isinstance(tool_result, dict) else {"result": str(tool_result)}

        # Photos
        mem_ctx = raw.get("memory_context") or {}
        if raw.get("photos_requested") or mem_ctx.get("photos_requested"):
            session.photos_requested = True
        if raw.get("photos_received") or mem_ctx.get("photos_received"):
            session.photos_received = True

        # Append conversation turn
        if user_text:
            session.conversation_turns.append({
                "role": "user",
                "text": user_text,
                "intent": result.intent or "unknown",
            })
        if result.response:
            session.conversation_turns.append({
                "role": "assistant",
                "text": result.response[:200],
                "intent": result.intent or "unknown",
            })
        # Keep last 20 entries (10 turns)
        if len(session.conversation_turns) > 20:
            session.conversation_turns = session.conversation_turns[-20:]

        logger.info(
            f"[adapter writeback] auth={session.auth_level} verified={session.verified} "
            f"order={session.pending_order_id} needs_identity={session.needs_identity} "
            f"active_intent={session.active_intent} issue_type={session.issue_type} "
            f"session={session.session_id}"
        )

    # ── Response text guarantor ────────────────────────────────────────────────

    def _ensure_response_text(self, result: RuntimeResponse, user_text: str) -> str:
        """Invariant: successful path always has speakable text."""
        text = (result.response or "").strip()
        user_norm = (user_text or "").strip().lower()

        if text and text.strip().lower() == user_norm:
            text = ""

        if text:
            return text

        raw = result.raw or {}
        chal = raw.get("identity_challenge") or {}
        if isinstance(chal, dict) and (chal.get("message") or "").strip():
            return str(chal["message"]).strip()

        if raw.get("needs_identity") or result.identity_blocked:
            return (
                "Please share your Order ID and the phone number or email "
                "used when placing the order."
            )

        auth = (result.auth_level or raw.get("auth_level") or "").lower()
        oid = result.order_id or raw.get("resolved_order_id")
        if auth in ("identified", "verified"):
            prefix = f"Thanks, I verified order {oid}. " if oid else "Thanks, I verified your details. "
            return prefix + "Please share a clear photo of the damage to continue."

        missing = raw.get("missing_inputs") or result.missing_inputs or []
        if "photos" in missing:
            return "Please upload clear photos of the damaged product so we can proceed."

        if result.error:
            return "Sorry, I'm having trouble with that right now. Please try again."

        return "Sorry, I could not generate a reply. Please try again."

    # ── Voice response shaper ─────────────────────────────────────────────────

    def _shape_for_tts(self, text: str) -> str:
        if not text:
            return ""
        from voice.processors.response import shape_for_voice
        return shape_for_voice(text, max_sentences=2)

    # ── Thinking phrase dispatch ──────────────────────────────────────────────

    def _maybe_emit_thinking_phrase(
        self,
        intent: Optional[str],
        intent_type: Optional[str],
        tool_name: Optional[str],
        requires_tool: bool,
    ) -> Optional[str]:
        """
        Emit a thinking phrase to TTS if this turn requires a tool call.
        Returns the phrase emitted (or None).
        """
        if not requires_tool:
            return None
        from voice.processors.thinking_utterance import get_thinking_phrase
        phrase = get_thinking_phrase(intent=intent, tool_name=tool_name, requires_tool=requires_tool)
        if phrase and self.on_thinking_phrase:
            try:
                self.on_thinking_phrase(phrase)
            except Exception as e:
                logger.warning(f"[thinking_phrase] callback failed: {e}")
        return phrase

    # ── Main entry point ──────────────────────────────────────────────────────

    def handle_transcript_sync(self, transcript: str, session: VoiceSession) -> RuntimeResponse:
        text = (transcript or "").strip()
        if not text:
            return RuntimeResponse(response="I didn't catch that. Could you say that again?")

        # Greeting fast-path (no LangGraph, no RAG, ~1ms)
        if self._is_greeting(text):
            logger.info(f"[adapter] greeting short-circuit text={text!r}")
            from voice.observability import VoiceObserver
            resp = self._greeting_response(session)
            # Still record the conversation turn for context
            session.conversation_turns.append({"role": "user", "text": text, "intent": "greeting"})
            session.conversation_turns.append({"role": "assistant", "text": resp.response, "intent": "greeting"})
            VoiceObserver.log_runtime_reply(resp.response, latency_ms=1.0, intent="greeting")
            VoiceObserver.log_writeback(session)
            return resp

        # Pre-extract order ID / contact from raw text (helps identity gate)
        from identity.service import extract_order_id, extract_contact
        extracted_oid = extract_order_id(text)
        if extracted_oid:
            session.pending_order_id = str(extracted_oid)
        extracted_contact = extract_contact(text)
        if extracted_contact:
            session.pending_contact = str(extracted_contact)

        ctx = self._build_context(text, session)
        from voice.observability import VoiceObserver
        VoiceObserver.log_context(ctx)
        VoiceObserver.log_runtime_start()

        # ── Thinking phrase (Phase 3) ─────────────────────────────────────────
        # Determine from memory + text whether a tool will be needed
        active_intent = session.active_intent or session.issue_type or ""
        is_affirmation = any(
            text.lower().strip().rstrip("!.,?") == tok
            for tok in ("yes", "yeah", "yep", "ok", "okay", "sure", "go ahead", "please")
        )
        # If affirmation continuing an action intent, or explicit action intent detected
        requires_tool_pre = (
            (is_affirmation and active_intent in ("return", "refund", "cancel", "track", "damaged_return"))
            or any(kw in text.lower() for kw in ("where is my order", "track my", "cancel my order",
                                                   "initiate return", "shopify"))
        )
        tool_name_pre = None
        if active_intent in ("track", "order_status") or "where is my order" in text.lower():
            tool_name_pre = "shopify_get_order"
        elif active_intent in ("return", "damaged_return") and is_affirmation:
            tool_name_pre = "shopify_initiate_return"

        thinking_phrase = self._maybe_emit_thinking_phrase(
            intent=active_intent or None,
            intent_type=None,
            tool_name=tool_name_pre,
            requires_tool=requires_tool_pre,
        )

        # ── Runtime invocation ────────────────────────────────────────────────
        t_r0 = time.time()
        result = self.runtime.handle(ctx)
        t_runtime_ms = (time.time() - t_r0) * 1000.0

        # ── Session writeback ─────────────────────────────────────────────────
        self._write_back_session(session, result, text)

        # ── Shape response for TTS ─────────────────────────────────────────────
        result.response = self._shape_for_tts(
            self._ensure_response_text(result, text)
        )

        VoiceObserver.log_runtime_reply(result.response, latency_ms=t_runtime_ms, intent=result.intent)
        VoiceObserver.log_writeback(session)
        logger.info(f"[runtime→voice] reply={result.response!r}")

        # Log per-turn trace
        self._log_turn_trace(
            session=session,
            user_text=text,
            result=result,
            runtime_ms=t_runtime_ms,
            thinking_phrase=thinking_phrase,
        )

        return result

    def _log_turn_trace(
        self,
        session: VoiceSession,
        user_text: str,
        result: RuntimeResponse,
        runtime_ms: float,
        thinking_phrase: Optional[str],
    ) -> None:
        """Emit a structured per-turn trace to terminal."""
        raw = result.raw or {}
        trace = VoiceTurnTrace(
            call_id=session.call_id,
            session_id=session.session_id,
            turn_number=session.turn_count + 1,
            user_utterance=user_text,
            intent=result.intent or raw.get("intent"),
            intent_type=raw.get("intent_type"),
            is_continuation=bool(raw.get("is_continuation")),
            thinking_phrase=thinking_phrase,
            rag_used=bool(raw.get("rag_prefetched") and raw.get("prefetched_docs")),
            rag_docs_retrieved=len(raw.get("prefetched_docs") or []),
            identity_required=bool(raw.get("needs_identity")),
            tool_name=session.last_tool_name,
            tool_result=session.last_tool_result,
            tool_success=bool(session.last_tool_result),
            response_text=result.response or "",
            runtime_latency_ms=runtime_ms,
            escalated=bool(result.escalated),
            blocked=bool(result.blocked),
        )
        trace.compute_ttfa()
        trace.log_to_terminal()

    async def handle_transcript(self, transcript: str, session: VoiceSession) -> RuntimeResponse:
        """Async entry point — runs sync handler in a thread pool."""
        import asyncio
        return await asyncio.to_thread(self.handle_transcript_sync, transcript, session)