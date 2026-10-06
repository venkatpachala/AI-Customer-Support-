# Ship D2C Support

Hosted control plane around the existing agent kernel. A brand uploads rules, connects a shop in sandbox, runs one refund, approves it, and pastes a widget. Mock tools only. Card charges are not enabled.

## Host

Public pilot, mock tools, free Render web service: https://d2c-support-agent-0360.onrender.com

`TOOLS_MODE=mock`. Shopify is unset. `/health` returns ok. The free instance sleeps after 15 idle minutes and wakes on the next request. Do not upgrade the service or add a paid database. Card charges are not enabled.

Owner sign-up is `POST /signup` (email and password). Sign-in is `POST /login` and sets `d2c_owner`. The seeded Zepto door remains `ops@zepto.local` with `OPS_PASSWORD` for the pilot script.

## URLs

| Path | What it is |
| --- | --- |
| `/` | Public page |
| `/docs` | Bearer auth, the four calls, the sandbox script, refund statuses |
| `/openapi.json` | OpenAPI. Swagger is `/swagger` |
| `/login` | Owner sign-in. Lands on `/app/inbox` |
| `/signup` | Creates a tenant, a widget test key, and a supervisor test key |
| `/app/inbox` | Interactions |
| `/app/cases/{case_id}` | Timeline |
| `/app/approvals` | Same queue as `/ops` |
| `/app/sandbox` | Presets and the pilot script |
| `/app/knowledge` | PDF upload |
| `/app/connections` | Sandbox badges. Tokens shown as last4 |
| `/app/install` | Keys, widget snippet, webhook, kill switch |
| `/w/{tenant}` | Customer widget |
| `/widget.js?tenant={tenant}` | Iframe injector |
| `/health` | `status=ok` with Shopify env unset |
| `/v1/sessions` `/v1/chat` `/v1/cases/{id}` `/v1/approvals` | Product API |

## Seed

```bash
python -m controlplane.seed
```

Prints the Zepto test widget key and the test supervisor key once. Later runs print prefixes only.

Owner login: `ops@zepto.local` / `OPS_PASSWORD`.

Local API:

```bash
uvicorn gateway.main:app --host 0.0.0.0 --port 8000
```

`TOOLS_MODE` defaults to mock. SQLite default is `sqlite:///./data/d2c_agent.db`. Postgres is used when `DATABASE_URL` is set (`docker compose up`).

## Sandbox script

`POST /v1/sandbox/run` with the test key, or **Run pilot script** on `/app/sandbox`.

1. What is the return policy for damaged products?
2. My order #12345 is damaged. I want to return it.
3. Order 12345, phone 9999900000, refund 2500, photos uploaded.

Pass only when the first turn has a citation, the second asks for photos, and the third is `workflow_status=waiting_approval` with no Stripe success. That pass sets `tenants.sandbox_passed_at`. A failure does not.

## Allowed homepage claims

The public page may say only:

- The reply cites the brand policy.
- A damaged return asks for photos.
- A refund above the auto cap, including ₹2500, stays `waiting_approval` until a person approves it.
- Tools in this deployment are mock. A person approves a refund before it is paid.

Do not claim WhatsApp, voice, or a live refund. Do not say a refund completed unless `workflow_status` is `succeeded`.

## Env

See `deployments/env.example`. Required in production: `TOOLS_MODE=mock`, `DATABASE_URL`, `OPS_PASSWORD`, `OPS_SESSION_SECRET`. Shopify and Stripe secrets are not required for `/health` and must not be baked into the image.

`d2c_test_` forces mock tools. `d2c_live_` returns 403 until the sandbox has passed. Issuing a live key does not turn on card charges.

## Deploy

Render: `deployments/render.yaml`. Fly: `deployments/fly.toml`. Both set mock mode and HTTPS. Put secrets in the host, then:

```bash
python -m controlplane.seed
```

Run the sandbox on that host as a human before you treat a live key as usable. Live Stripe is a later change. It is not done.
