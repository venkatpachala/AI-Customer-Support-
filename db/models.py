from datetime import datetime
from typing import Optional

from sqlalchemy import (
    String,
    Text,
    Boolean,
    Float,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class SessionRow(Base):
    __tablename__ = "sessions"

    session_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    cases = relationship("CaseRow", back_populates="session", cascade="all, delete-orphan")
    messages = relationship("MessageRow", back_populates="session", cascade="all, delete-orphan")


class CaseRow(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)

    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    issue_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    missing_inputs: Mapped[dict] = mapped_column(JSON, default=list)
    photos_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    photos_received: Mapped[bool] = mapped_column(Boolean, default=False)

    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    tools_executed: Mapped[dict] = mapped_column(JSON, default=list)
    tool_results_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    policy_citations: Mapped[dict] = mapped_column(JSON, default=list)

    auth_level: Mapped[str] = mapped_column(String(32), default="anonymous")
    last_agent_action: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    session = relationship("SessionRow", back_populates="cases")


class MessageRow(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    role: Mapped[str] = mapped_column(String(32))  # user | assistant | system
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)

    session = relationship("SessionRow", back_populates="messages")


class InteractionRow(Base):
    __tablename__ = "interactions"
    __table_args__ = (
        Index("ix_interactions_tenant_created", "tenant_id", "created_at"),
    )

    interaction_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="chat")

    message: Mapped[str] = mapped_column(Text)
    response: Mapped[str] = mapped_column(Text)

    intent: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    risk_level: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    order_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    missing_inputs: Mapped[dict] = mapped_column(JSON, default=list)
    photos_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    photos_received: Mapped[bool] = mapped_column(Boolean, default=False)

    tools_used: Mapped[dict] = mapped_column(JSON, default=list)
    tool_statuses: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_results_summary: Mapped[dict] = mapped_column(JSON, default=dict)

    escalated: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    escalation_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    citations: Mapped[dict] = mapped_column(JSON, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="open")
    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)

class ToolCallRow(Base):
    __tablename__ = "tool_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    tool_call_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    request_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)

    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operation: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    params_json: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(32), default="started", index=True)  # started|success|error|skipped
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, default=1)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    side_effecting: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)