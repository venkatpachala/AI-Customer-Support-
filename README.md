# D2C Customer AI Support Agent

![Python](https://img.shields.io/badge/Python-3.12-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.115-green)
![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-purple)
![LangSmith](https://img.shields.io/badge/LangSmith-Tracing-orange)
![Prometheus](https://img.shields.io/badge/Prometheus-Metrics-red)
![Grafana](https://img.shields.io/badge/Grafana-Dashboard-orange)
![Ollama](https://img.shields.io/badge/Ollama-qwen2.5:7b-black)
![Pinecone](https://img.shields.io/badge/Pinecone-RAG-teal)
![Status](https://img.shields.io/badge/Status-MVP%20Ready-brightgreen)

Production-oriented multi-agent Customer Support system for D2C / Quick Commerce brands.

This system handles real support workflows such as returns, refunds, cancellations, and policy questions with planning, tool execution, policy grounding, escalation, observability, and evaluation.

---

## Features

- Multi-Agent Architecture using LangGraph
- Structured Planning with dependencies and missing-input detection
- Tool Execution Engine with retries, timeouts, and parallel execution
- Policy-Grounded Responses using RAG over company documents
- Human-in-the-Loop (HITL) for high-value and high-risk cases
- Guardrails for PII, prompt injection, and out-of-scope queries
- Multi-Tenant Configuration (brand tone, approval thresholds, etc.)
- Full Observability
  - Structured JSON logs
  - LangSmith traces
  - Prometheus metrics
  - Grafana dashboards
- Automated Evaluation with golden set regression testing

---

## System Architecture

```text
User / Client
      │
      ▼
AI Gateway (FastAPI /chat)
      │
      ▼
Guardrails
(PII / Injection / Out-of-scope)
      │
      ▼
Supervisor
(Intent + Risk)
      │
      ▼
Planner
(Structured Execution Plan)
      │
      ▼
Execution Engine
(Tools + Retries + Parallel Execution)
      │
      ▼
Verifier
(Soft vs Hard issues)
      │
      ▼
HITL Check
(Escalate if needed)
      │
      ▼
QA Agent
(Policy + Tool Grounded Response)
      │
      ▼
Final Response