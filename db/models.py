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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.session import Base


def _utcnow() -> datetime:
    return datetime.utcnow()


class CustomerSessionRow(Base):
    """Public widget session. The client cannot choose its auth level."""

    __tablename__ = "customer_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_ref: Mapped[str] = mapped_column(String(128), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


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

    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

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


# Cases in these statuses are still the customer's journey. A resolved case
# is not in this set and must not be reused for a new order problem.
# waiting_approval and running_workflow are accepted now so a later workflow
# engine can park a case without splitting it. Nothing writes them yet.
OPEN_CASE_STATUSES = (
    "open",
    "waiting_customer",
    "waiting_approval",
    "running_workflow",
    "escalated",
)

# workflow_runs.status
WORKFLOW_RUN_STATUSES = (
    "pending",
    "running",
    "waiting_approval",
    "retrying",
    "succeeded",
    "failed",
    "cancelled",
)

# human_tasks.type
HUMAN_TASK_TYPES = (
    "refund_approval",
    "identity_review",
    "fraud_review",
    "policy_exception",
)

HUMAN_TASK_STATUSES = ("pending", "approved", "rejected")


class PlatformTenantRow(Base):
    """Cached copy of a platform tenant contract. YAML on disk is the source."""

    __tablename__ = "platform_tenants"

    tenant_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PlatformCustomerRow(Base):
    """Customer directory inside one tenant. external_id is the support customer id."""

    __tablename__ = "platform_customers"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_id", name="uq_platform_customer_external"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    external_id: Mapped[str] = mapped_column(String(128), index=True)
    contact: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    auth_level: Mapped[str] = mapped_column(String(32), default="anonymous")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class PlatformConversationRow(Base):
    """Binds a channel session to the case it is working, including across sessions.

    The case row keeps the session that opened it. This table is how a later
    chat or voice session points at that same case without a new column on
    ``sessions`` (SQLite create_all would not add one).
    """

    __tablename__ = "platform_conversations"
    __table_args__ = (
        UniqueConstraint("session_id", "case_id", name="uq_platform_conversation_session_case"),
        Index("ix_platform_conversations_session_created", "session_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    customer_id: Mapped[str] = mapped_column(String(128), index=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    channel: Mapped[str] = mapped_column(String(32), default="chat")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class WorkflowRunRow(Base):
    """One execution of a named workflow for a case.

    status: pending | running | waiting_approval | retrying | succeeded | failed | cancelled
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_tenant_case", "tenant_id", "case_id"),
        Index("ix_workflow_runs_status", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    workflow_name: Mapped[str] = mapped_column(String(128), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, unique=True)
    current_step: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    steps = relationship("WorkflowStepRow", back_populates="run", cascade="all, delete-orphan")


class WorkflowStepRow(Base):
    """One step attempt inside a workflow run."""

    __tablename__ = "workflow_steps"
    __table_args__ = (
        Index("ix_workflow_steps_run_index", "run_id", "step_index"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("workflow_runs.id"), index=True)
    step_name: Mapped[str] = mapped_column(String(128))
    step_index: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    attempt: Mapped[int] = mapped_column(Integer, default=1)
    input_json: Mapped[dict] = mapped_column(JSON, default=dict)
    output_json: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    run = relationship("WorkflowRunRow", back_populates="steps")


class HumanTaskRow(Base):
    """Approval queue. type: refund_approval | identity_review | fraud_review | policy_exception.

    status: pending | approved | rejected
    """

    __tablename__ = "human_tasks"
    __table_args__ = (
        Index("ix_human_tasks_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(ForeignKey("cases.case_id"), nullable=True, index=True)
    workflow_run_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("workflow_runs.id"), nullable=True, index=True
    )
    task_type: Mapped[str] = mapped_column("type", String(64), index=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    resolution_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class EvidenceRow(Base):
    """Citation or QA span attached to a case. Unused until the knowledge phase."""

    __tablename__ = "evidence"
    __table_args__ = (
        Index("ix_evidence_case", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    interaction_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    citation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    span_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class PlatformEventRow(Base):
    """Append-only typed event log for a tenant. payload_json holds the body."""

    __tablename__ = "platform_events"
    __table_args__ = (
        Index("ix_platform_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_platform_events_case", "case_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    session_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(128), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)


class TenantAccountRow(Base):
    """Hosted brand. The API key names this row. YAML policy files stay on disk."""

    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), default="")
    sandbox_passed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    killed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class OwnerAccountRow(Base):
    """Person who signed up. The password is a hash. The row points at one tenant."""

    __tablename__ = "owner_accounts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(256), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ApiKeyRow(Base):
    """Bearer credential. The raw secret is stored only until the install page shows it once."""

    __tablename__ = "api_keys"
    __table_args__ = (
        UniqueConstraint("key_hash", name="uq_api_keys_hash"),
        Index("ix_api_keys_tenant_role", "tenant_id", "role"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    prefix: Mapped[str] = mapped_column(String(32), index=True)
    key_hash: Mapped[str] = mapped_column(String(64))
    role: Mapped[str] = mapped_column(String(32))  # widget | supervisor
    mode: Mapped[str] = mapped_column(String(16))  # test | live
    reveal_once: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class WebhookEndpointRow(Base):
    __tablename__ = "webhook_endpoints"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(String(128))
    last_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class WebhookDeliveryRow(Base):
    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    endpoint_id: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    case_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class KnowledgeSnapshotRow(Base):
    __tablename__ = "knowledge_snapshots"
    __table_args__ = (
        Index("ix_knowledge_snapshots_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(256))
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="ingested")
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class ConnectionRow(Base):
    """Shop credentials. Templates read last4 only."""

    __tablename__ = "tenant_connections"
    __table_args__ = (
        UniqueConstraint("tenant_id", "provider", name="uq_tenant_connection_provider"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    shop_domain: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    token_last4: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    secret_value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)