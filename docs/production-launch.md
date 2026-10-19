# Production launch and evidence

## What this implementation supplies

The operator desk uses the Python service as its data authority. New database
tenants do not require files in the repository. Uploaded PDFs and chunks are
stored transactionally in SQL; all active documents form the collection.
Deleting a source removes it from retrieval immediately. This intentionally
replaces the disconnected upload-to-local-pickle path. BM25 is the default;
`KNOWLEDGE_EMBEDDINGS=openai` adds stored dense vectors and RRF using
`text-embedding-3-small`. The old Pinecone benchmark is not a measurement of
this new upload path. Rebenchmark it before making quality claims.

Customer sessions use opaque server-generated visitor identities. An optional
`Authorization: Session <session_id>` header supports same-origin iframe fetches
when third-party cookies are blocked. It grants customer access only. Never
embed supervisor keys. Operator replies, takeover, release and resolution are
persistent. The customer widget polls operator messages.

Real order access requires a short-lived email code delivered to the contact
obtained from Shopify, not an address supplied by the customer. The worker must
be running and SMTP configured. Images are private case evidence; saying
"photos uploaded" does not satisfy live workflows. Sandbox fixtures retain that
shortcut. Live refunds remain disabled by default.

Approval decisions use compare-and-set updates and enqueue a resume job in the
same transaction. Workflow execution uses database leases with heartbeat and
ownership checks. Provider idempotency keys remain stable per run. Webhooks
are retried independently with event IDs, bounded backoff and dead-letter state.
An email/webhook failure never repeats a refund.

## Local verification

Use Python 3.12+ and Node 22+:

```powershell
uv sync --frozen
uv run pytest tests -q --disable-warnings
Set-Location web
npm ci --ignore-scripts
npm run typecheck
npm test
npm run build
```

The tests create an isolated temporary database and forbid paid model calls
unless a test supplies a double. `tests/browser_server.py` is an explicitly
fake-model browser fixture and MUST NOT be deployed. It tests persistence,
transport, rendering and operator journeys, not model quality.

Run real integration checks separately with real model and provider sandbox
credentials, and record the commit/configuration/dataset used. A green mock
suite is not evidence that merchant credentials work.

## Hosting

1. Deploy `web/` to its existing Vercel target. Set server-only
   `D2C_API_ORIGIN=https://api.example.com`, and `VITE_AUTH_ENABLED=false` for the
   Python-owner-auth deployment. Do not expose the API key or DB URL with VITE_
   prefixes. The support app uses its `/signup` and `/login` backend routes;
   template federated auth is not the support account authority.
2. Copy `deployments/production.env.example` to an untracked production secret
   file, or supply equivalent secrets from the host. Generate distinct random
   DB passwords, a session signing secret, and a Fernet key. Configure HTTPS,
   the public UI origin, model provider and SMTP. Keep live refunds disabled.
3. Provision PostgreSQL with separate migration and application roles. The app
   role must not be a superuser or have BYPASSRLS. For a new Docker volume the
   compose template creates the restricted role. Existing databases require
   equivalent grants by the administrator; init scripts do not rerun on an
   existing volume.
4. From the repository root:

```powershell
docker compose --env-file deployments/production.env -f compose.production.yml up -d --build
```

5. Put the API behind an HTTPS reverse proxy. Configure trusted proxy IPs
   explicitly; never trust arbitrary forwarded headers. `PUBLIC_APP_URL` is
   the UI origin used for cookie mutation origin checks. In addition to
   application checks, enforce request-body limits and public network egress
   policy at the host. Webhooks require an approved host and reject redirects;
   deny internal/metadata egress at infrastructure level too.
6. `/health` is liveness, `/ready` checks DB/schema and the worker heartbeat.
   Configure external checks. Do not mark the service healthy solely because
   the process starts. Deployment secrets must fail validation at startup.

## Release gates

Run migrations once before rolling out API/worker instances. Production startup
checks the schema instead of performing DDL. Use a fresh PostgreSQL staging
database and the same restricted role as production. Run tenant isolation,
concurrent decisions, lease recovery, upload/delete and browser journeys.
`EVAL_HTTP=1` requires a reachable API; it fails rather than silently skipping.
The HTTP golden scripts now create authenticated sessions. Their mock-provider
results are regression evidence, not a measurement of live-model quality. Use
`python -m evaluation.product_eval --help` for a current authenticated product
evaluation and explicitly enable a semantic judge when appropriate. Do not
substitute historical reports for current evidence.

Launch with one invited brand and supervised requests. Test registration,
document upload, a question, unknown-question abstention, verification, evidence,
takeover, reply, resolution, restart and cross-tenant denials. Compare draft AI
answers with the operator's judgment before enabling direct answers broadly.

Do not enable payment execution until the merchant's real payment-system mapping,
partial refund balance, test-mode contract, uncertain-result reconciliation and
crash recovery have been verified. Merely setting PAYMENT_INTEGRATION_VERIFIED
is not proof. The current implementation safely gates this capability; a
merchant-specific reconciliation integration is still a launch condition for
real money movement. Policy eligibility is not payment authorization.

## Recovery and operations

- Back up PostgreSQL with the host's scheduled backups/PITR. Restore into a
  separate instance, run tenant-scoped read checks and record recovery duration.
  This document does not claim a successful production restore drill.
- Keep credential encryption keys in a secret store, backed up separately.
  CREDENTIAL_ENCRYPTION_KEYS is comma-separated, newest first. New writes use
  the first key; old keys allow decryption during rotation. Legacy v1 ciphertext
  needs the original session secret until connections are re-saved as v2.
- Inspect delivery_outbox for dead jobs. Fix the root cause before an operator
  requeues one. Do not delete idempotency records to force another payment.
- On provider timeout, inspect the provider state using the existing operation
  key/reference. Escalate ambiguous payment outcomes instead of inventing a
  success or submitting an unrelated new refund.
- Kill a tenant's chat/action capability during an incident. Preserve audit
  records. Deploy the previous application image only after checking schema
  compatibility; do not automatically reverse migrations containing user data.
- Retain only needed customer messages/evidence. The purge path includes new
  knowledge content, attachment, verification, operator and delivery tables.

## Evidence for a portfolio claim

Publish the tested commit, architecture decisions, current evaluation report,
release checks, latency distribution, token/cost per case, real pilot volume,
operator correction rate, incident notes and restore drill. Clearly distinguish
fixtures, sandbox providers and real users. No real customer conversations,
tokens or attachments belong in a public repository or demo.


## Verification recorded for this change

- An isolated `uv sync --frozen` environment installed the declared dependencies.
- Backend: 147 tests passed, including atomic refund budget contention, exact
  Shopify order matching, customer ownership, approval replay and support intake.
- Frontend: TypeScript and build passed; 252 tests passed and four optional
  exported-template documentation tests were explicitly skipped.
- Desktop/mobile smoke checks passed on dev and the production build with
  no JavaScript errors, no horizontal overflow and no baseline divergence.
- The browser regression uses a fake model and an isolated SQL database.
- PostgreSQL 16 CI passed restricted-role case/message isolation, customer
  session capability lookup, pooled-connection reset and forbidden insertion.
  Docker was unavailable locally, so no local PostgreSQL result is claimed. The two-question real-model smoke passed, including unsupported-question
  abstention. Representative model evaluation, SMTP/Shopify/Stripe sandbox
  contracts, backup restore, load tests and public deployment remain gates.

Daily financial limits reserve capacity atomically before provider calls. A
reservation remains consumed after a crash, rejection or uncertain result.
This conservative behavior can stop further refunds until reconciliation; it
must never be bypassed by deleting idempotency records. Automatic real-money
execution remains disabled pending merchant reconciliation integration.

The frontend repository is maintained separately at
https://github.com/venkatpachala/Fronte-end-D2C. `web/` is the matching integration
snapshot used by the combined browser CI. Deploy the frontend with the same
revision and `D2C_API_ORIGIN` pointing to the corresponding Python service.
