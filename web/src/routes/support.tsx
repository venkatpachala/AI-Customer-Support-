import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { Page } from "@/components/site/frame";
export const Route = createFileRoute("/support")({ component: Support });
function Support() {
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit() {
    setBusy(true); setStatus("");
    try {
      const response = await fetch("/v1/desk/support", { method: "POST", credentials: "include",
        headers: { "content-type": "application/json" }, body: JSON.stringify({ email, note }) });
      const body = await response.json() as { id?: string; detail?: unknown };
      if (!response.ok) throw new Error(response.status === 401 ? "Sign in before submitting a support request." :
        typeof body.detail === "string" ? body.detail : "Check your email and description, then retry.");
      setStatus(`Request ${body.id} received. A person must review it; no payment action was retried.`);
      setNote("");
    } catch (error) { setStatus(error instanceof Error ? error.message : "Request failed. Please retry."); }
    finally { setBusy(false); }
  }
  return <Page eyebrow="Support" title="Report a stuck case." lede="Sign in to submit a request for your brand. Include the case ID and what happened.">
    <form className="max-w-xl space-y-4" onSubmit={(event) => { event.preventDefault(); void submit(); }}>
      <label className="block text-sm">Reply email<input type="email" required value={email}
        onChange={(event) => setEmail(event.target.value)} className="mt-1 h-11 w-full rounded border border-line bg-elev px-3" /></label>
      <label className="block text-sm">What happened<textarea required minLength={5} maxLength={2000} value={note}
        onChange={(event) => setNote(event.target.value)} rows={5} className="mt-1 w-full rounded border border-line bg-elev p-3" /></label>
      <p className="text-sm text-muted">Do not include passwords, payment card details, or verification codes.</p>
      <button disabled={busy} className="h-11 rounded bg-accent px-4 text-ink">{busy ? "Submitting…" : "Submit request"}</button>
      {status && <p role="status" className="text-sm text-muted">{status}</p>}
    </form>
  </Page>;
}
