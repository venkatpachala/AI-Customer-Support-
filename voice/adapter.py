import re
import time
from typing import Any, Dict, Optional

from loguru import logger

from runtime.context import RequestContext, AuthContext
from runtime.response import RuntimeResponse
from voice.context import VoiceSession


class SupportRuntimeAdapter:
    def __init__(self, runtime: Any):
        self.runtime = runtime

    def _is_greeting(self, text: str) -> bool:
        t = (text or "").strip().lower()
        return t in {"hi", "hello", "hey", "hi!", "hello!", "hey!"} or t in {
            "good morning",
            "good afternoon",
            "good evening",
        }

    def _greeting_response(self, session: VoiceSession) -> RuntimeResponse:
        return RuntimeResponse(
            response="Hi! I can help with orders, returns, refunds, or policy questions.",
            confidence=1.0,
            session_id=session.session_id,
            case_id=session.case_id,
            auth_level=session.auth_level,
            intent="greeting",
        )

    def _build_memory_context(self, session: VoiceSession) -> Dict[str, Any]:
        return {
            "auth_level": session.auth_level,
            "verified": session.verified,
            "verified_customer": session.verified_customer,
            "verified_order_ids": list(session.verified_order_ids or []),
            "pending_order_id": session.pending_order_id,
            "pending_contact": session.pending_contact,
            "customer_contact": session.customer_contact,
            "active_order_id": session.pending_order_id,
            "needs_identity": session.needs_identity,
            "issue_type": session.issue_type,
            "intent": session.issue_type,
        }

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

    def _write_back_session(self, session: VoiceSession, result: RuntimeResponse) -> None:
        if result.session_id:
            session.session_id = result.session_id
        if result.case_id:
            session.case_id = result.case_id

        # Auth ladder
        if result.auth_level:
            session.auth_level = str(result.auth_level).lower().strip()
        raw = result.raw or {}
        if "verified" in raw:
            session.verified = bool(raw.get("verified"))
        if "verified_customer" in raw:
            session.verified_customer = bool(raw.get("verified_customer"))
        session.normalize_auth()

        # Orders
        from identity.service import extract_order_id, extract_contact
        oid = result.order_id or raw.get("resolved_order_id") or raw.get("order_id") or raw.get("pending_order_id")
        if not oid:
            oid = extract_order_id(raw.get("message") or "")
        if oid:
            session.pending_order_id = str(oid)
            if session.auth_level in ("identified", "verified"):
                if str(oid) not in session.verified_order_ids:
                    session.verified_order_ids.append(str(oid))

        # Contact: candidate vs established
        contact = raw.get("customer_contact") or raw.get("pending_contact")
        if not contact:
            contact = extract_contact(raw.get("message") or "")
        if contact:
            session.pending_contact = str(contact)
            if session.auth_level in ("identified", "verified"):
                session.customer_contact = str(contact)

        session.needs_identity = bool(
            getattr(result, "needs_identity", None)
            if getattr(result, "needs_identity", None) is not None
            else raw.get("needs_identity", session.needs_identity)
        )

        # Sticky issue type
        intent = (result.intent or raw.get("intent") or "").lower().strip()
        if intent and intent not in ("greeting", "general", "policy", "faq"):
            session.issue_type = intent
        elif raw.get("issue_type"):
            session.issue_type = str(raw.get("issue_type"))

        logger.info(
            f"[adapter writeback] auth={session.auth_level} verified={session.verified} "
            f"order={session.pending_order_id} needs_identity={session.needs_identity} "
            f"issue_type={session.issue_type} session={session.session_id}"
        )

    def _ensure_response_text(self, result: RuntimeResponse, user_text: str) -> str:
        """Invariant: successful path always has speakable text."""
        text = (result.response or "").strip()
        user_norm = (user_text or "").strip().lower()

        # Drop pure echo of user
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
                "Please share your Order ID and the phone or email "
                "used when placing the order."
            )

        auth = (result.auth_level or raw.get("auth_level") or "").lower()
        oid = result.order_id or raw.get("resolved_order_id")
        if auth in ("identified", "verified"):
            prefix = f"Thanks, I verified order {oid}. " if oid else "Thanks, I verified your order. "
            return prefix + "Please upload clear photos of the damage so we can continue."

        missing = raw.get("missing_inputs") or result.missing_inputs or []
        if "photos" in missing:
            return "Please upload clear photos of the damaged product so we can proceed."

        if result.error:
            return "Sorry, I'm having trouble with that right now. Please try again."

        return "Sorry, I could not generate a reply. Please try again."

    def _shape_for_tts(self, text: str) -> str:
        if not text:
            return ""
        # Use the dedicated voice response shaper
        from voice.processors.response import shape_for_voice
        return shape_for_voice(text, max_sentences=2)

    def handle_transcript_sync(self, transcript: str, session: VoiceSession) -> RuntimeResponse:
        text = (transcript or "").strip()
        if not text:
            return RuntimeResponse(response="I didn't catch that. Could you say that again?")

        if self._is_greeting(text):
            logger.info(f"[adapter] greeting short-circuit text={text!r}")
            from voice.observability import VoiceObserver
            resp = self._greeting_response(session)
            VoiceObserver.log_runtime_reply(resp.response, latency_ms=1.0, intent="greeting")
            VoiceObserver.log_writeback(session)
            return resp

        ctx = self._build_context(text, session)
        from voice.observability import VoiceObserver
        VoiceObserver.log_context(ctx)
        VoiceObserver.log_runtime_start()

        from identity.service import extract_order_id, extract_contact
        extracted_oid = extract_order_id(text)
        if extracted_oid:
            session.pending_order_id = str(extracted_oid)
        extracted_contact = extract_contact(text)
        if extracted_contact:
            session.pending_contact = str(extracted_contact)

        t_r0 = time.time()
        result = self.runtime.handle(ctx)
        t_runtime_ms = (time.time() - t_r0) * 1000.0

        self._write_back_session(session, result)

        result.response = self._shape_for_tts(
            self._ensure_response_text(result, text)
        )
        VoiceObserver.log_runtime_reply(result.response, latency_ms=t_runtime_ms, intent=result.intent)
        VoiceObserver.log_writeback(session)
        logger.info(f"[runtime→voice] reply={result.response!r}")
        return result

    async def handle_transcript(self, transcript: str, session: VoiceSession) -> RuntimeResponse:
        """Async entry point — runs sync runtime in a thread pool to avoid blocking the event loop."""
        import asyncio
        return await asyncio.to_thread(self.handle_transcript_sync, transcript, session)