import { createFileRoute } from "@tanstack/react-router";
import { Page } from "@/components/site/frame";

export const Route = createFileRoute("/security")({ component: Security });

const ROWS = [
  ["Tenant source", "Authenticated operator credentials or an opaque customer session determine access."],
  ["Mismatch", "403 on chat and case reads when the body names another brand."],
  ["Empty filter", "Retrieval with no tenant returns no chunks."],
  ["Keys", "The console shows prefixes. Raw secrets are not rendered back."],
  ["Money", "Each brand has explicit policy limits. Real payments are disabled pending merchant validation."],
  ["Kill switch", "A disabled brand gets 403 on the next chat."],
  ["Cap", "Default 2,000 chats a day. Past that, 429."],
  ["WhatsApp", "Shown as unavailable. There is no save button."],
];

function Security() {
  return (
    <Page
      eyebrow="Security"
      title="Isolation is a test, not a slogan."
      lede="Access controls are enforced by the API. Saved provider credentials are encrypted; production requires configured encryption keys and HTTPS."
    >
      <div className="overflow-hidden rounded-lg border border-line">
        {ROWS.map(([k, v]) => (
          <div key={k} className="grid gap-1 border-b border-line px-4 py-4 last:border-b-0 md:grid-cols-4">
            <div className="text-sm">{k}</div>
            <div className="text-sm text-muted md:col-span-3">{v}</div>
          </div>
        ))}
      </div>
    </Page>
  );
}
