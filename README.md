<h1 align="center">D2C Customer AI Support Agent </h1>

<p align="center">
  <em>A production-oriented, multi-agent AI system for D2C and Quick Commerce brands to automate support workflows.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/LangGraph-Multi--Agent-purple.svg" alt="LangGraph">
  <img src="https://img.shields.io/badge/LangSmith-Tracing-orange.svg" alt="LangSmith">
  <img src="https://img.shields.io/badge/Prometheus-Metrics-e6522c.svg?logo=prometheus" alt="Prometheus">
  <img src="https://img.shields.io/badge/Grafana-Dashboard-f46800.svg?logo=grafana" alt="Grafana">
  <img src="https://img.shields.io/badge/Ollama-qwen2.5:7b-black.svg?logo=ollama" alt="Ollama">
  <img src="https://img.shields.io/badge/Pinecone-RAG-00a8e8.svg" alt="Pinecone">
  <img src="https://img.shields.io/badge/Status-MVP%20Ready-brightgreen.svg" alt="Status">
</p>

---

## Overview

The **D2C Customer AI Support Agent** is a state-of-the-art, multi-agent customer support system tailored for Direct-to-Consumer (D2C) and Quick Commerce platforms. Built on modern agentic frameworks, it autonomously handles real-world support workflows including returns, refunds, order cancellations, and policy inquiries.

With a strong focus on enterprise requirements, it integrates **planning**, **tool execution**, **policy grounding**, **human-in-the-loop (HITL) escalation**, **robust guardrails**, and **comprehensive observability**.

---

## Key Features

- **Multi-Agent Orchestration**: Powered by [LangGraph](https://python.langchain.com/docs/langgraph), orchestrating intent detection, planning, execution, verification, and QA agents.
- **Structured Planning**: Dynamic dependency resolution and missing-input detection for complex multi-step workflows.
- **Resilient Tool Execution Engine**: Supports retries, timeouts, and parallel execution of external tools (e.g., Shopify, Stripe).
- **Policy-Grounded Responses**: Retrieval-Augmented Generation (RAG) using company documents via Pinecone to ensure accurate answers.
- **Enterprise Guardrails**: Built-in protections against Prompt Injections, out-of-scope queries, and PII leakage.
- **Human-in-the-Loop (HITL)**: Automatic escalations for high-risk, high-value, or unresolved edge cases.
- **Multi-Tenant Configuration**: Easily adapt the agent's tone, approval thresholds, and toolsets per brand.
- **Full Observability & Telemetry**: Deep tracing via LangSmith, structured JSON logging, and Prometheus/Grafana integration.
- **Automated Evaluation**: Golden set regression testing to ensure continuous improvement and zero regressions.

---

## System Architecture

The agent's workflow follows a directed acyclic graph (DAG) structure ensuring step-by-step reasoning, validation, and safe execution.

```mermaid
graph TD
    %% Define Styles
    classDef client fill:#3498db,stroke:#2980b9,stroke-width:2px,color:white;
    classDef gateway fill:#2ecc71,stroke:#27ae60,stroke-width:2px,color:white;
    classDef guardrail fill:#e74c3c,stroke:#c0392b,stroke-width:2px,color:white;
    classDef agent fill:#9b59b6,stroke:#8e44ad,stroke-width:2px,color:white;
    classDef execution fill:#f1c40f,stroke:#f39c12,stroke-width:2px,color:black;
    classDef external fill:#34495e,stroke:#2c3e50,stroke-width:2px,color:white;

    %% Nodes
    User(["User / Client Request"])
    API["AI Gateway FastAPI"]
    Guard["Guardrails PII / Prompt Injection"]
    Supervisor["Supervisor Agent Intent & Risk"]
    Planner["Planner Agent Structured Execution Plan"]
    Engine["Execution Engine Tools / Parallel Processing"]
    Shopify[("Shopify API")]
    Stripe[("Stripe API")]
    Verifier["Verifier Agent Soft vs Hard Issues"]
    HITL{"Human-in-the-Loop Escalate?"}
    QA["QA Agent Policy & Grounded Response"]
    Response(["Final Output to User"])
    HumanAgent(["Human Agent Escalate"])

    %% Edges
    User --> API
    API --> Guard
    Guard --> Supervisor
    Supervisor --> Planner
    Planner --> Engine
    Engine <--> Shopify
    Engine <--> Stripe
    Engine --> Verifier
    Verifier --> HITL
    HITL -- Yes --> HumanAgent
    HITL -- No --> QA
    QA --> Response

    %% Assign Classes
    class User,Response client;
    class API gateway;
    class Guard,HITL guardrail;
    class Supervisor,Planner,Verifier,QA agent;
    class Engine execution;
    class Shopify,Stripe external;
```

### Core Components

1. **AI Gateway (`gateway/`)**: A FastAPI-based REST API that handles incoming user requests, manages websockets for streaming, and authenticates clients.
2. **Orchestration (`orchestration/`)**: The LangGraph DAG definition (`graph.py`). Contains specific node implementations:
   - `supervisor.py`: Detects intent and assigns tasks.
   - `planner.py`: Breaks down tasks into a structured JSON plan.
   - `execution.py`: Executes tool calls safely.
   - `verifier.py`: Verifies if the executed tools resolved the user query.
   - `hitl.py`: Manages escalation flows.
3. **Tools (`tools/`)**: Integrations with external SaaS (e.g., Shopify, Stripe) and internal databases.
4. **Agents (`agents/`)**: Specialized sub-agents (e.g., `qa.py` for synthesizing answers).
5. **RAG (`rag/`)**: Document chunking, embedding generation, and Pinecone vector store integration.

---

## Project Structure

```text
.
├── agents/             # Specialized agent definitions (QA, etc.)
├── attachments/        # User attachment parsing and handling
├── common/             # Shared utilities and helpers
├── config/             # Multi-tenant and system configurations
├── deployments/        # K8s, Docker deployment manifests
├── evaluation/         # Regression tests and LangSmith evaluators
├── frontend/           # Sample UI for interacting with the AI Agent
├── gateway/            # FastAPI entry points and API routers
├── llm/                # LLM client wrappers (Ollama, OpenAI)
├── memory/             # Conversation history and state management
├── observability/      # Logging, Prometheus metrics, OpenTelemetry
├── orchestration/      # LangGraph state machine and execution nodes
├── rag/                # Document retrieval and Pinecone integration
├── security/           # Guardrails (PII, Prompt Injection detection)
├── tests/              # Unit and integration test suites
├── tools/              # External API integrations (Shopify, Stripe)
├── main.py             # Application entry point
├── pyproject.toml      # Dependency management (uv)
└── docker-compose.yml  # Local development stack (Redis, Postgres, Prometheus)
```

---

## Getting Started

### Prerequisites

- **Python 3.12+**
- **[uv](https://github.com/astral-sh/uv)** (Recommended for fast dependency management)
- **Docker & Docker Compose** (for running Redis, Postgres, Prometheus locally)
- Access to an LLM provider (Ollama running locally or an OpenAI API key)

### Installation

1. **Clone the repository:**
   ```bash
   git clone <your-repo-url>
   cd D2C
   ```

2. **Set up the environment:**
   We recommend using `uv` to sync dependencies:
   ```bash
   uv sync
   # Or create a virtual environment manually:
   # python -m venv .venv
   # source .venv/bin/activate
   # pip install -r requirements.txt
   ```

3. **Configure Environment Variables:**
   Create a `.env` file in the root directory (you can copy `.env.example` if available) and add your keys:
   ```ini
   # LLM Providers
   OPENAI_API_KEY="your-openai-api-key"
   OLLAMA_BASE_URL="http://localhost:11434"

   # Vector Store
   PINECONE_API_KEY="your-pinecone-api-key"

   # External Tools
   SHOPIFY_ACCESS_TOKEN="your-shopify-token"
   STRIPE_API_KEY="your-stripe-key"
   
   # Tracing
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_API_KEY="your-langsmith-key"
   LANGCHAIN_PROJECT="d2c-support-agent"
   ```

### Running Locally

1. **Start the Infrastructure Dependencies:**
   Launch Redis (for caching/memory), Prometheus, and Grafana via Docker Compose:
   ```bash
   docker-compose up -d
   ```

2. **Start the FastAPI Server:**
   ```bash
   uv run uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```

3. **Access the API:**
   - Swagger Documentation: [http://localhost:8000/docs](http://localhost:8000/docs)
   - Health Check: [http://localhost:8000/health](http://localhost:8000/health)

---

## Observability

This project strongly emphasizes observability to safely run AI in production.

- **Metrics**: Prometheus exposes metrics at `/metrics` (tracked in `observability/`).
- **Dashboards**: Grafana is configured in `docker-compose.yml` to scrape Prometheus.
- **Tracing**: LangSmith captures all agent reasoning steps, tool payloads, and latency.

---

## Testing & Evaluation

Run the test suite using `pytest`:

```bash
uv run pytest
```

For regression testing against the golden dataset (evaluating the agent's RAG and tool-use performance):

```bash
uv run python -m evaluation.run_evals
```

---

## Contributing

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---
