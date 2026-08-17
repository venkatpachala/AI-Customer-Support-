from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional

from langchain_core.messages import HumanMessage

from runtime.context import RequestContext
from runtime.events import RuntimeEvent, RuntimeEventType
from runtime.response import RuntimeResponse


class SupportRuntime:
    """
    Single entrypoint for all channels.

    Phase 0:
    - invoke_agent(ctx, inputs): gateway-owned short-circuits + shared graph invoke
    - handle(ctx): fuller path for future channels (voice can start here later)
    """

    def __init__(
        self,
        graph_invoker: Callable[[Dict[str, Any]], Dict[str, Any]],
        *,
        memory_service: Any = None,
        interaction_service: Any = None,
        load_tenant_config: Optional[Callable[[str], Dict[str, Any]]] = None,
        new_request_id: Optional[Callable[[], str]] = None,
        log_event: Optional[Callable[..., None]] = None,
        apply_output_guard: Optional[Callable[[str], str]] = None,
    ):
        self.graph_invoker = graph_invoker
        self.memory_service = memory_service
        self.interaction_service = interaction_service
        self.load_tenant_config = load_tenant_config or (lambda _t: {})
        self.new_request_id = new_request_id or (lambda: f"req_{int(time.time() * 1000)}")
        self.log_event = log_event
        self.apply_output_guard = apply_output_guard or (lambda x: x)
        self._events: list[RuntimeEvent] = []

    def _emit(self, event: RuntimeEvent) -> None:
        self._events.append(event)
        if self.log_event:
            try:
                self.log_event(
                    event.type.value,
                    event.request_id,
                    data=event.data,
                )
            except Exception:
                pass

    def get_events(self) -> list[RuntimeEvent]:
        return list(self._events)

    def clear_events(self) -> None:
        self._events.clear()

    def invoke_agent(self, ctx: RequestContext, inputs: Dict[str, Any]) -> RuntimeResponse:
        """
        Phase 0 core path used by gateway /chat.

        Gateway owns:
        - policy cache
        - sticky escalation
        - high-value verification short-circuit
        - detailed memory writeback / response formatting

        Runtime owns:
        - channel-agnostic graph invocation
        - runtime events around the agent brain
        """
        request_id = ctx.request_id or self.new_request_id()
        ctx.request_id = request_id

        inputs = dict(inputs or {})
        inputs.setdefault("request_id", request_id)
        inputs.setdefault("channel", ctx.channel or "chat")
        inputs.setdefault("tenant_id", ctx.tenant_id)
        inputs.setdefault("customer_id", ctx.customer_id)
        if ctx.session_id:
            inputs.setdefault("session_id", ctx.session_id)
        if ctx.case_id:
            inputs.setdefault("case_id", ctx.case_id)

        # Ensure auth fields are present for identity_gate
        inputs.setdefault("auth_level", ctx.auth.auth_level)
        inputs.setdefault("verified", ctx.auth.verified)
        inputs.setdefault("verified_order_ids", list(ctx.auth.verified_order_ids or []))

        self._emit(
            RuntimeEvent(
                type=RuntimeEventType.REQUEST_RECEIVED,
                request_id=request_id,
                session_id=ctx.session_id,
                tenant_id=ctx.tenant_id,
                channel=ctx.channel,
                data={
                    "via": "invoke_agent",
                    "customer_id": ctx.customer_id,
                    "message_preview": (ctx.message or "")[:120],
                },
            )
        )

        try:
            result = self.graph_invoker(inputs) or {}

            escalated = bool(result.get("needs_escalation") or result.get("escalated"))
            blocked = bool(result.get("blocked"))
            intent = result.get("intent") or (result.get("current_plan") or {}).get("intent")

            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.RESPONSE_READY,
                    request_id=request_id,
                    session_id=ctx.session_id or inputs.get("session_id"),
                    tenant_id=ctx.tenant_id,
                    channel=ctx.channel,
                    data={
                        "via": "invoke_agent",
                        "escalated": escalated,
                        "blocked": blocked,
                        "intent": intent,
                        "identity_blocked": bool(result.get("identity_blocked")),
                    },
                )
            )

            return RuntimeResponse(
                response="",  # gateway formats final customer text in Phase 0
                confidence=float(result.get("confidence") or 0.0),
                citations=list(result.get("citations") or []),
                escalated=escalated,
                blocked=blocked,
                reason=result.get("escalation_reason"),
                tool_results=result.get("tool_results") or {},
                request_id=request_id,
                session_id=ctx.session_id or inputs.get("session_id"),
                case_id=ctx.case_id or inputs.get("case_id"),
                missing_inputs=list(result.get("missing_inputs") or []),
                auth_level=result.get("auth_level") or ctx.auth.auth_level,
                identity_blocked=bool(result.get("identity_blocked")),
                intent=intent,
                risk_level=result.get("risk_level"),
                status=None,
                order_id=result.get("resolved_order_id") or result.get("order_id"),
                raw=result,
            )

        except Exception as e:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.REQUEST_FAILED,
                    request_id=request_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    channel=ctx.channel,
                    data={"via": "invoke_agent", "error": str(e)},
                )
            )
            raise

    def handle(self, ctx: RequestContext) -> RuntimeResponse:
        """
        Fuller channel entry (future voice/WhatsApp can use this).
        Phase 0 chat prefers invoke_agent() so gateway can keep R1 short-circuits.
        """
        started = time.time()
        request_id = ctx.request_id or self.new_request_id()
        ctx.request_id = request_id

        self._emit(
            RuntimeEvent(
                type=RuntimeEventType.REQUEST_RECEIVED,
                request_id=request_id,
                session_id=ctx.session_id,
                tenant_id=ctx.tenant_id,
                channel=ctx.channel,
                data={"via": "handle", "message": ctx.message, "customer_id": ctx.customer_id},
            )
        )

        session = None
        case = None

        try:
            if self.memory_service is not None:
                # Compatible with current MemoryService signatures
                try:
                    session = self.memory_service.get_or_create_session(
                        customer_id=ctx.customer_id,
                        tenant_id=ctx.tenant_id,
                        session_id=ctx.session_id,
                    )
                except TypeError:
                    session = self.memory_service.get_or_create_session(
                        session_id=ctx.session_id,
                        customer_id=ctx.customer_id,
                        tenant_id=ctx.tenant_id,
                    )

                try:
                    case = self.memory_service.get_or_create_active_case(session)
                except TypeError:
                    case = self.memory_service.get_or_create_active_case(
                        session=session,
                        customer_id=ctx.customer_id,
                        tenant_id=ctx.tenant_id,
                    )

                ctx.session_id = session.session_id
                ctx.case_id = getattr(case, "case_id", None)

                try:
                    self.memory_service.append_message(session, role="user", content=ctx.message)
                except TypeError:
                    try:
                        self.memory_service.append_message(
                            session_id=session.session_id,
                            case_id=ctx.case_id,
                            role="user",
                            content=ctx.message,
                        )
                    except Exception:
                        pass

                memory_context = self.memory_service.to_state_context(session, case) or {}
            else:
                memory_context = {}

            memory_context["auth_level"] = ctx.auth.auth_level
            memory_context["verified_order_ids"] = list(ctx.auth.verified_order_ids or [])

            tenant_config = self.load_tenant_config(ctx.tenant_id) or {}
            if hasattr(tenant_config, "dict"):
                tenant_config = tenant_config.dict()

            inputs: Dict[str, Any] = {
                "messages": [HumanMessage(content=ctx.message)],
                "memory_context": memory_context,
                "tenant_config": tenant_config,
                "current_plan": None,
                "workflow_steps": [],
                "tool_results": {},
                "confidence": 0.0,
                "citations": [],
                "risk_level": "low",
                "needs_escalation": False,
                "escalation_reason": "",
                "verification_passed": True,
                "verification_issues": [],
                **ctx.to_graph_seed(),
            }

            # Reuse invoke_agent for the actual brain call
            runtime_result = self.invoke_agent(ctx, inputs)
            result = runtime_result.raw or {}

            response_text = ""
            messages = result.get("messages") or []
            if messages:
                last = messages[-1]
                response_text = getattr(last, "content", None) or str(last)
            response_text = self.apply_output_guard(response_text or "")

            escalated = bool(result.get("needs_escalation") or result.get("escalated"))
            blocked = bool(result.get("blocked"))
            missing_inputs = list(result.get("missing_inputs") or [])
            tool_results = result.get("tool_results") or {}
            citations = result.get("citations") or []
            confidence = float(result.get("confidence") or 0.0)
            intent = result.get("intent") or (result.get("current_plan") or {}).get("intent")
            order_id = result.get("resolved_order_id") or result.get("order_id")

            status = "escalated" if escalated else ("blocked" if blocked else "open")
            if missing_inputs:
                status = "waiting_customer"

            if self.memory_service is not None and case is not None:
                try:
                    self.memory_service.update_case_from_result(
                        case,
                        order_id=order_id,
                        issue_type=intent,
                        missing_inputs=missing_inputs,
                        tools_executed=list(tool_results.keys()),
                        tool_results_summary={
                            k: {"status": (v or {}).get("status")}
                            for k, v in tool_results.items()
                            if isinstance(v, dict)
                        },
                        policy_citations=citations,
                        escalated=escalated,
                        escalation_reason=result.get("escalation_reason"),
                        status=status,
                        last_agent_action="responded",
                    )
                except Exception:
                    pass

                try:
                    self.memory_service.append_message(session, role="assistant", content=response_text)
                except TypeError:
                    try:
                        self.memory_service.append_message(
                            session_id=ctx.session_id,
                            case_id=ctx.case_id,
                            role="assistant",
                            content=response_text,
                        )
                    except Exception:
                        pass

            latency_ms = (time.time() - started) * 1000.0
            if self.interaction_service is not None and ctx.session_id:
                try:
                    self.interaction_service.log_chat_turn(
                        conversation_id=ctx.session_id,
                        case_id=ctx.case_id,
                        tenant_id=ctx.tenant_id,
                        customer_id=ctx.customer_id,
                        message=ctx.message,
                        response=response_text,
                        intent=intent,
                        risk_level=result.get("risk_level"),
                        order_id=order_id,
                        missing_inputs=missing_inputs,
                        photos_requested="photos" in missing_inputs,
                        photos_received=False,
                        tool_results=tool_results,
                        escalated=escalated,
                        blocked=blocked,
                        escalation_reason=result.get("escalation_reason"),
                        citations=citations,
                        confidence=confidence,
                        latency_ms=latency_ms,
                        status=status,
                        request_id=request_id,
                        metadata={"channel": ctx.channel, "via": "handle"},
                    )
                except Exception:
                    pass

            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.RESPONSE_READY,
                    request_id=request_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    channel=ctx.channel,
                    data={
                        "via": "handle",
                        "escalated": escalated,
                        "blocked": blocked,
                        "intent": intent,
                        "latency_ms": round(latency_ms, 2),
                    },
                )
            )

            return RuntimeResponse(
                response=response_text,
                confidence=confidence,
                citations=citations,
                escalated=escalated,
                blocked=blocked,
                reason=result.get("escalation_reason"),
                tool_results=tool_results,
                request_id=request_id,
                session_id=ctx.session_id,
                case_id=ctx.case_id,
                missing_inputs=missing_inputs,
                auth_level=result.get("auth_level") or ctx.auth.auth_level,
                identity_blocked=bool(result.get("identity_blocked")),
                intent=intent,
                risk_level=result.get("risk_level"),
                status=status,
                order_id=order_id,
                raw=result,
            )

        except Exception as e:
            self._emit(
                RuntimeEvent(
                    type=RuntimeEventType.REQUEST_FAILED,
                    request_id=request_id,
                    session_id=ctx.session_id,
                    tenant_id=ctx.tenant_id,
                    channel=ctx.channel,
                    data={"via": "handle", "error": str(e)},
                )
            )
            return RuntimeResponse(
                response="",
                request_id=request_id,
                session_id=ctx.session_id if ctx else None,
                error=str(e),
                escalated=False,
            )