import { createFileRoute } from "@tanstack/react-router";
import { Page } from "@/components/site/frame";

export const Route = createFileRoute("/privacy")({ component: Privacy });

function Privacy() {
  return (
    <Page
      eyebrow="Privacy"
      title="Brand data in this preview stays in your browser."
      lede="Cases, uploads, and last-four connection digits are stored locally on this device. The chat endpoint receives the message and the session tenant, not a shop token."
    >
      <div className="max-w-2xl space-y-4 text-sm text-muted">
        <p>Do not paste real customer data, card numbers, or live API secrets. The connection form keeps only four digits.</p>
        <p>A deletion note in Support clears the local workspace. It does not call Stripe.</p>
        <p>Server logs for this preview are the status and chat handlers. They are not a production audit store.</p>
      </div>
    </Page>
  );
}
