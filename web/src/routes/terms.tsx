import { createFileRoute } from "@tanstack/react-router";
import { Page } from "@/components/site/frame";

export const Route = createFileRoute("/terms")({ component: Terms });

function Terms() {
  return (
    <Page
      eyebrow="Terms"
      title="Sandbox terms for this preview."
      lede="Archal in this preview does not move money, does not call live Shopify or Stripe, and does not store real customer credentials."
    >
      <div className="max-w-2xl space-y-4 text-sm text-muted">
        <p>Answers are grounded in the brand snapshot you upload here, or in the Northline sample. They can be wrong. A person still owns refunds above the cap.</p>
        <p>Approving a case marks it held. It is not a completed refund. Do not tell a customer otherwise.</p>
        <p>Voice, WhatsApp, and self-serve live charges are not offered.</p>
      </div>
    </Page>
  );
}
