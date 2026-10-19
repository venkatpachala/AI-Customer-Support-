# Integrated support product

The frontend and backend changes are linked in backend PR #2 and frontend PR #1.
This is a supervised pilot implementation. It has not been publicly deployed.
Use `production-launch.md` for deployment configuration and operational gates.

## Request architecture

```text
Storefront iframe / operator browser
        -> TanStack frontend, same-origin /v1 proxy
        -> FastAPI: credential resolution, origin checks, tenant scope, quotas
        -> ChatService: session lease, input digest, idempotent response replay
        -> existing support graph: routing, identity, policy, tools, generation
        -> SQL: cases, messages, active policy collection, workflow state
        -> durable jobs: verification email, webhook, workflow recovery
```

The Python API owns support data. The frontend's earlier alternate mock support
backend no longer creates a separate version of cases or refund decisions.
Framework authentication helpers remain available to their template deployment
mode; the support product uses Python owner accounts.

## Main user journeys

1. A brand owner registers and receives an owner session. The brand can be
   configured from SQL without adding a tenant YAML file to the repository.
2. The owner uploads a PDF. The API validates its signature, size and page/chunk
   limits, then stores document bytes and parsed chunks transactionally. All
   active documents contribute to retrieval. Removing a document removes its
   retrieval eligibility immediately.
3. The installed iframe creates an opaque customer session. A Session header
   supports browsers that block third-party cookies. The customer cannot choose
   another customer's identity or use this capability for operator APIs.
4. Chat uses the shared support graph. BM25 retrieves tenant policy chunks by
   default; optional stored dense vectors add reciprocal-rank fusion. Citations
   identify the uploaded document, page and clause. Missing policy evidence can
   return an explicit abstention. There is no simulated token streaming.
5. An operator opens the case, takes over and sends a persisted operator message.
   The customer widget receives it by polling. Further customer messages on a
   human-owned case bypass generation. Resolution is stored in the backend.
6. Real order disclosure requires a short-lived code sent to the merchant's
   registered order email. Codes are session/order/case-bound, attempt-limited
   and single-use. A typed claim that photographs were uploaded does not satisfy
   a live workflow; evidence must be uploaded through the private endpoint.

## API boundaries

| Surface | Purpose | Access |
| --- | --- | --- |
| `/signup`, `/login`, `/logout` | Owner authentication | Rate-limited public entry |
| `/v1/me` | Authenticated brand context | Owner/key |
| `/w/{tenant}/session` | Create a customer capability | Enabled brand, server-generated visitor |
| `/v1/chat` | Customer support turn | Customer session or authorized product key |
| `/v1/knowledge` | List/upload/delete policy sources | Brand staff |
| `/v1/desk/cases` | Inbox, detail, takeover, reply, resolution | Brand staff |
| `/v1/desk/settings` | Brand tone and policy limits | Brand staff |
| `/v1/desk/support` | Durable support intake | Brand staff |
| `/v1/customer/*` | Verification, evidence and message delivery | Owning customer session |
| `/health`, `/ready` | Liveness, DB/worker readiness | Infrastructure |

PostgreSQL policies enforce tenant boundaries on sensitive support tables and
their child rows. Pre-tenant customer authentication exposes only the exact
opaque session record being presented, using a transaction-local setting.
Production rejects a database role that is a superuser or bypasses RLS.

## Workflow reliability and financial boundaries

Database leases serialize execution and recover abandoned jobs after expiry.
Approval decisions update only pending tasks and enqueue recovery work in the
same transaction. Tool execution preserves tenant and provider-mode context
across worker threads. Repeated payment attempts use a stable provider
idempotency key; immutable completed inputs cannot be silently changed.

Daily refund capacity is reserved atomically across workflows. Uncertain or
failed attempts retain their reservation until reconciliation establishes the
provider outcome. This can conservatively stop additional refunds. It avoids
assuming a timeout means no money moved.

Live refunds are disabled by default. Customer verification, policy eligibility,
automation enablement, current merchant payment mapping, remaining balance and
administrator gates all apply. A merchant-specific mapping/reconciliation
adapter and provider sandbox tests are still required for real money movement.
Approval by itself is not proof that a refund occurred.

Email and webhook delivery run independently through a persistent outbox with
deduplication, bounded retry and dead-letter state. Delivery failure cannot
restart a completed financial action. The worker must run alongside the API.

## Verified evidence and its limits

- The frontend passed TypeScript, build and 252 tests; four optional template
  documentation tests were explicitly skipped because those files are absent.
- Desktop/mobile smoke passed on development and production builds. The browser
  journey exercised registration, PDF upload, cited chat, operator reply,
  resolution and access denial with a fake model and real isolated persistence.
- PostgreSQL 16 CI passed restricted-role case/message isolation, exact-session
  lookup, pooled-connection reset and forbidden cross-tenant insertion.
- A real `gpt-4o-mini` smoke test answered one synthetic policy question with a
  citation and abstained on an unsupported question. Observed request durations
  were 3.38 s and 1.94 s; this is two samples, not a production latency SLO.
- Python and frontend production-dependency audits reported no known
  vulnerabilities after the dependency refresh. The Python audit now blocks CI.

The historical RAG benchmark does not measure this new SQL upload/retrieval
path. The quality UI provides deterministic checks, not semantic correctness or
tone scores. The product evaluation command supports explicit semantic judging;
human-labeled data, representative provider contracts, load tests and pilot
traffic are still needed before making outcome claims.

## Run locally on Windows

Use separate PowerShell terminals for API, worker and frontend. Give API and
worker the same environment. For development, a new SQLite database avoids
touching an existing local database:

```powershell
Set-Location D:\D2C
uv sync --frozen
uv run python -m controlplane.dev_setup
$env:DATABASE_URL = "sqlite:///./data/local-support.db"
$env:LLM_PROVIDER = "openai"
$env:SUPERVISOR_MODEL = "gpt-4o-mini"
$env:PLANNER_MODEL = "gpt-4o-mini"
$env:QA_MODEL = "gpt-4o-mini"
$env:TOOLS_MODE = "mock"
$env:KNOWLEDGE_EMBEDDINGS = "none"
uv run python -m db.migrate
uv run uvicorn gateway.main:app --host 127.0.0.1 --port 8000
```

Supply the API credential through your untracked environment. To use Ollama,
set `LLM_PROVIDER=ollama` and all three role models to an installed model such
as `qwen2.5:3b`. Mixing OpenAI with Qwen model names is rejected.

```powershell
# Another terminal, with the same backend environment:
uv run --env-file .env python -m controlplane.worker

# Frontend terminal:
Set-Location D:\D2C\web
$env:D2C_API_ORIGIN = "http://127.0.0.1:8000"
npm ci --ignore-scripts
npm run dev
```

Open `http://127.0.0.1:8080/enter`, register your own brand, upload a policy, and
use the Install page's widget URL. Test fixtures are not application servers and
must never be deployed. Production requires PostgreSQL, HTTPS, secrets, worker
readiness, restore verification and the release gates in the launch runbook.


For a visible interactive walkthrough with a new synthetic brand and sample
policy, keep the API, worker and frontend running, then use:

```powershell
Set-Location D:\D2C
uv run python tests/make_browser_pdf.py
Set-Location web
node scripts/local-product-demo.mjs
```

This opens separate operator and customer windows and exercises the configured
model, citation display, takeover and human replies. It leaves both windows open.
Synthetic account details are saved only under the ignored `artifacts/` folder.
