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

## Rotate a key

On `/app/install`, create a new test widget key. The previous raw key is not shown again. Revoke a leaked key by issuing a replacement and treating the old prefix as dead. Connection tokens are replaced by saving the provider form again. The page keeps the last four characters.

## Disable a tenant

On `/app/install`, use Disable chat. `/v1/chat` for that tenant returns 403. Enable chat turns it back on. This does not call Stripe.

## Read a failed sandbox

Open `/app/sandbox` after Run pilot script. A pass needs a citation, a photo ask, and `waiting_approval` with no Stripe success. The failure text is the judge reason on that page. `tenants.sandbox_passed_at` stays empty when the script fails.

## Roll back a deploy

Redeploy the previous green commit on the Render service. Do not flip `TOOLS_MODE` to live to "fix" a red sandbox. A red `python -m evaluation.release_gate` blocks the next deploy.

## Live tools

Live shop calls stay off until the sandbox has passed and an admin submits the host `OPS_PASSWORD` on `/app/install`. A live key without that flag still uses test tools. Refunds above the auto cap stay `waiting_approval`. A second approve does not call Stripe again.

## Keep Stripe in test

Leave `STRIPE_MODE` unset or set `STRIPE_MODE=test`. A live secret (`sk_live_...`) is refused unless `STRIPE_MODE=live` is set on purpose. Do that only after one week on test with the brand's real orders. `TOOLS_MODE=mock` does not need Shopify or Stripe secrets.

## Open a run

`GET /v1/workflows/{run_id}` with header `X-Tenant-Id: zepto`. `status` is `waiting_approval` while a supervisor still has to decide. The same id is still there after an API restart.
