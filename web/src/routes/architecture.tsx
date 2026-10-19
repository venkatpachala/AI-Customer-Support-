import { createFileRoute } from "@tanstack/react-router";
import { Page } from "@/components/site/frame";

export const Route = createFileRoute("/architecture")({ component: Architecture });

const LAYERS = [
  { n: "Edge", d: "Session, widget path, or owner cookie picks the tenant. Body tenant_id is ignored or rejected." },
  { n: "Runtime", d: "Intent, missing inputs, and the refund cap. Tools are skipped when the case must wait." },
  { n: "Knowledge", d: "Retrieval without a tenant filter returns nothing. Another brand’s clauses never appear." },
  { n: "Tools", d: "Credentials come from the brand row. A Stripe key in the chat body is dropped." },
  { n: "Audit", d: "Each turn records tenant, case, tool status, and latency. Logs carry the same ids." },
];

function Architecture() {
  return (
    <Page
      eyebrow="Architecture"
      title="The model does not choose the brand."
      lede="Production support systems establish identity once, then force it through retrieval, tools, memory, and cost. Archal’s preview implements that contract."
    >
      <ol className="space-y-3">
        {LAYERS.map((layer, i) => (
          <li key={layer.n} className="grid gap-2 rounded-lg border border-line bg-elev p-4 md:grid-cols-12 md:items-center">
            <span className="font-mono text-sm text-accent md:col-span-1">0{i + 1}</span>
            <span className="text-lg md:col-span-3">{layer.n}</span>
            <span className="text-sm text-muted md:col-span-8">{layer.d}</span>
          </li>
        ))}
      </ol>
      <p className="mt-8 max-w-2xl text-sm text-muted">
        This preview keeps brand rows in the browser so you can switch tenants without an account. The chat and approval endpoints still run on the server and refuse a mismatched tenant.
      </p>
    </Page>
  );
}
