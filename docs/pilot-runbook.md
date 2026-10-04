# Pilot runbook

One brand. Chat only. Stripe stays in test mode until a week of real orders has been reviewed.

## Money

- Auto refund cap is ₹2000. A verified damaged order at or under that cap, with the required photos, can refund without a person.
- Manager cap is ₹10000. ₹2001 to ₹10000 stays `waiting_approval` until a supervisor approves in `/ops`.
- ₹10001 and above never pays, even if someone approves.
- The daily live cap is ₹20000 per tenant. Over that cap the run stays `waiting_approval` and Stripe is not called.
- Stripe runs once per workflow run. The idempotency key is `{run_id}:execute_refund`.

## Who may open /ops

Set `OPS_USER` and `OPS_PASSWORD` in the API environment. Those two people sign in at `/ops`. The cookie is `d2c_ops`, role `supervisor`, for 8 hours. The customer widget has no link to this page. A customer session cookie cannot approve.

## What the customer hears

- Waiting on photos: ask only for photos of the damaged item. Do not say a refund was issued.
- Waiting on approval: a person will review the refund. Do not say a refund was issued and do not invent a Stripe refund id.
- Ownership failed: "could not verify this order". Do not read back the phone or email on the order.

## Reject

In `/ops`, write a note, then Reject. The note is required. The workflow run becomes `cancelled` and Stripe is not called.

## Keep Stripe in test

Leave `STRIPE_MODE` unset or set `STRIPE_MODE=test`. A live secret (`sk_live_...`) is refused unless `STRIPE_MODE=live` is set on purpose. Do that only after one week on test with the brand's real orders. `TOOLS_MODE=mock` does not need Shopify or Stripe secrets.

## Open a run

`GET /v1/workflows/{run_id}` with header `X-Tenant-Id: zepto`. `status` is `waiting_approval` while a supervisor still has to decide. The same id is still there after an API restart.
