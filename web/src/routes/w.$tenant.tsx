import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
export const Route = createFileRoute("/w/$tenant")({ component: Widget });
type Turn = { id?: number; role: string; text: string };
function Widget() {
  const { tenant } = Route.useParams();
  const [session, setSession] = useState("");
  const [caseId, setCaseId] = useState("");
  const [message, setMessage] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [order, setOrder] = useState("");
  const [challenge, setChallenge] = useState("");
  const [code, setCode] = useState("");
  const headers: Record<string, string> = session ? { Authorization: `Session ${session}` } : {};

  useEffect(() => {
    if (!session || !caseId || busy) return;
    let active = true;
    const poll = async () => {
      try {
        const response = await fetch(`/v1/customer/cases/${encodeURIComponent(caseId)}/messages`, {
          headers: { Authorization: `Session ${session}` }, signal: AbortSignal.timeout(10000),
        });
        if (response.ok) {
          const data = await response.json() as { items: Turn[] };
          if (active && data.items.length) setTurns(data.items);
        }
      } catch { /* Keep the existing conversation during a transient disconnect. */ }
    };
    void poll();
    const timer = window.setInterval(() => void poll(), 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [session, caseId, busy]);

  async function send() {
    if (!message.trim() || busy) return;
    const text = message.trim(); setMessage(""); setBusy(true); setNote("");
    setTurns((rows) => [...rows, { role: "user", text }]);
    try {
      let token = session;
      if (!token) {
        const response = await fetch(`/w/${encodeURIComponent(tenant)}/session`, {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ customer_ref: "visitor" }),
        });
        const body = await response.json() as { session_id?: string; detail?: string };
        if (!response.ok || !body.session_id) throw new Error(body.detail || "Support is unavailable.");
        token = body.session_id; setSession(token);
      }
      const response = await fetch("/chat", {
        method: "POST", headers: { "content-type": "application/json", Authorization: `Session ${token}` },
        body: JSON.stringify({ message: text }), signal: AbortSignal.timeout(90000),
      });
      const body = await response.json() as { response?: string; detail?: string; case_id?: string };
      if (!response.ok) throw new Error(body.detail || "Please retry your message.");
      if (body.case_id) setCaseId(body.case_id);
      setTurns((rows) => [...rows, { role: "assistant", text: body.response || "Your request is being reviewed." }]);
    } catch (error) { setNote(error instanceof Error ? error.message : "Connection failed. Please retry."); }
    finally { setBusy(false); }
  }

  async function verify() {
    setBusy(true); setNote("");
    try {
      const response = await fetch(challenge ? `/v1/customer/verification/${challenge}` : "/v1/customer/verification", {
        method: "POST", headers: { ...headers, "content-type": "application/json" },
        body: JSON.stringify(challenge ? { code } : { case_id: caseId, order_id: order }),
      });
      const body = await response.json() as { detail?: string; message?: string; challenge_id?: string; verified?: boolean };
      if (!response.ok) throw new Error(body.detail || "Verification failed.");
      if (body.challenge_id) setChallenge(body.challenge_id);
      setNote(body.verified ? "Order verified. Send a message to continue your request." : body.message || "Check your registered email.");
    } catch (error) { setNote(error instanceof Error ? error.message : "Verification failed."); }
    finally { setBusy(false); }
  }

  async function upload(file: File) {
    setBusy(true); setNote("");
    try {
      const data = new FormData(); data.set("file", file);
      const response = await fetch(`/v1/customer/cases/${caseId}/evidence`, { method: "POST", headers, body: data });
      const body = await response.json() as { detail?: string };
      if (!response.ok) throw new Error(body.detail || "Upload failed.");
      setNote("Photo received. Send a message to continue your request.");
    } catch (error) { setNote(error instanceof Error ? error.message : "Upload failed."); }
    finally { setBusy(false); }
  }

  return <main className="mx-auto flex min-h-screen max-w-lg flex-col bg-bg p-4 text-fg">
    <h1 className="text-xl font-medium">Customer support</h1>
    <p className="mt-2 text-sm text-muted">Ask about store policies or an order. A support agent can review requests that need assistance.</p>
    <div aria-live="polite" className="my-5 flex-1 space-y-3">{turns.map((turn, index) =>
      <article key={turn.id || index} className={`rounded-lg border border-line p-3 ${turn.role === "user" ? "ml-6" : "mr-6"}`}>
        <p className="text-xs text-muted">{turn.role === "user" ? "You" : turn.role === "operator" ? "Support agent" : "AI assistant"}</p>
        <p className="mt-1 whitespace-pre-wrap text-sm">{turn.text}</p>
      </article>)}</div>
    {note && <p role="status" className="my-3 text-sm">{note}</p>}
    {caseId && <details className="mb-4 rounded-lg border border-line p-3"><summary className="cursor-pointer text-sm">Verify an order or upload a photo</summary>
      <div className="mt-3 space-y-2">
        <label className="block text-xs">Order number<input value={order} onChange={(e) => setOrder(e.target.value)} className="mt-1 h-10 w-full rounded border border-line bg-elev px-2" /></label>
        {challenge && <label className="block text-xs">Email verification code<input value={code} onChange={(e) => setCode(e.target.value)} inputMode="numeric" maxLength={6} className="mt-1 h-10 w-full rounded border border-line bg-elev px-2" /></label>}
        <button type="button" onClick={() => void verify()} disabled={busy || !order} className="h-10 rounded border border-line px-3 text-sm">{challenge ? "Confirm code" : "Send verification code"}</button>
        <label className="block text-sm">Photo of the item (PNG/JPEG, up to 5 MB)<input type="file" accept="image/png,image/jpeg" disabled={busy} onChange={(e) => { const file=e.target.files?.[0]; e.target.value=""; if(file) void upload(file); }} className="mt-2 block max-w-full text-xs" /></label>
      </div>
    </details>}
    <form onSubmit={(e) => { e.preventDefault(); void send(); }} className="flex gap-2">
      <input aria-label="Message" value={message} onChange={(e) => setMessage(e.target.value)} maxLength={8000} placeholder="How can we help?" className="h-11 min-w-0 flex-1 rounded-md border border-line bg-elev px-3" />
      <button disabled={busy || !message.trim()} className="h-11 rounded-md bg-accent px-4 text-ink disabled:opacity-50">{busy ? "Sending…" : "Send"}</button>
    </form>
  </main>;
}
