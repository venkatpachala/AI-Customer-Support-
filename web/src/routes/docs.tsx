import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Page } from "@/components/site/frame";

export const Route = createFileRoute("/docs")({ component: Docs });

const CALLS = [
  ["GET", "/health", "Service, tools mode, database."],
  ["GET", "/metrics", "Plain-text interaction count."],
  ["GET", "/widget.js?tenant=northline", "One script tag. Injects the brand iframe."],
  ["POST", "/signup", "Email, password, brand. Returns test keys once."],
  ["POST", "/login", "Owner session cookie."],
  ["POST", "/logout", "Clears the owner cookie."],
  ["POST", "/v1/sessions", "Bearer key. Sets the customer session cookie."],
  ["POST", "/w/{tenant}/session", "Path is the tenant. Body tenant cannot switch it."],
  ["POST", "/v1/chat", "Bearer or session. Policy reply, case id, workflow."],
  ["POST", "/chat", "Session cookie. Client auth fields are dropped."],
  ["GET", "/v1/cases/{id}", "Case, latest run, pending tasks."],
  ["GET", "/v1/cases/{id}/timeline", "Messages and approvals, oldest first."],
  ["GET", "/v1/cases/{id}/copilot", "Short brief for a person. No new agent."],
  ["GET", "/v1/approvals", "Supervisor queue."],
  ["POST", "/v1/approvals/{id}/approve", "Holds the refund. Stripe is not called."],
  ["POST", "/v1/approvals/{id}/reject", "Note required."],
  ["GET", "/v1/workflows/{run_id}", "Run and steps. Does not resume."],
  ["GET", "/v1/interactions", "Newest first. No tool secrets."],
  ["GET", "/v1/analytics/intents", "Intent counts for the key's brand."],
  ["GET", "/interactions/recent", "Cross-brand recent rows."],
  ["POST", "/v1/sandbox/run", "Three scripted turns on a test key."],
  ["GET", "/v1/knowledge", "Published snapshots."],
  ["POST", "/v1/knowledge", "Supervisor PDF upload, 8 MB."],
  ["GET", "/v1/webhooks", "Saved endpoint, if any."],
  ["POST", "/v1/webhooks", "https URL. Supervisor key."],
  ["POST", "/v1/tenant/kill", "Disable chat for the key's brand."],
  ["POST", "/v1/tenant/restore", "Enable it again."],
  ["POST", "/v1/ops/login", "Configured operator credentials. Prefer owner sign-in."],
  ["POST", "/support", "Stuck-case note. Does not charge."],
  ["POST", "/privacy/delete", "Queues an authenticated deletion request for review."],
];

function Docs() {
  const [out, setOut] = useState("No call yet.");
  const [busy, setBusy] = useState(false);

  async function call(path: string, init?: RequestInit) {
    setBusy(true);
    try {
      const response = await fetch(path, { ...init, headers: { accept: "application/json", ...(init?.headers ?? {}) } });
      const text = await response.text();
      setOut(`${response.status}\n${text.slice(0, 1200)}`);
    } catch (error) {
      setOut(error instanceof Error ? error.message : "Call failed.");
    }
    setBusy(false);
  }

  return (
    <Page
      eyebrow="API"
      title="The same calls the desk uses."
      lede="Sign up to create your own tenant and keys. Operator APIs require your authenticated session or a supervisor bearer key. Financial actions are disabled by default."
    >
      <div className="flex flex-col gap-2 sm:flex-row">
        <button type="button" disabled={busy} className="h-11 rounded-md bg-accent px-4 text-sm font-medium text-ink disabled:opacity-50" onClick={() => void call("/health")}>
          GET /health
        </button>
        <button
          type="button"
          disabled={busy}
          className="h-11 rounded-md border border-line px-4 text-sm disabled:opacity-50"
          onClick={() =>
            void call("/v1/approvals", { credentials: "include" })
          }
        >
          GET approvals
        </button>
        <button
          type="button"
          disabled={busy}
          className="h-11 rounded-md border border-line px-4 text-sm disabled:opacity-50"
          onClick={() =>
            void call("/v1/chat", {
              method: "POST",
              credentials: "include", headers: { "content-type": "application/json" },
              body: JSON.stringify({ message: "What is the return policy for damaged products?" }),
            })
          }
        >
          POST a policy question
        </button>
      </div>
      <pre className="mt-4 max-h-64 overflow-auto rounded-md border border-line bg-elev p-4 font-mono text-xs text-muted">{out}</pre>
      <div className="mt-8 overflow-hidden rounded-lg border border-line">
        {CALLS.map(([method, path, detail]) => (
          <div key={`${method} ${path}`} className="grid gap-1 border-b border-line px-4 py-3 last:border-b-0 md:grid-cols-12">
            <div className="font-mono text-xs text-accent md:col-span-2">{method}</div>
            <div className="font-mono text-sm md:col-span-5">{path}</div>
            <div className="text-sm text-muted md:col-span-5">{detail}</div>
          </div>
        ))}
      </div>
    </Page>
  );
}
