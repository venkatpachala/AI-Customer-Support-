import { createFileRoute, Link } from "@tanstack/react-router";
import { useState, type FormEvent } from "react";
import { SiteFrame } from "@/components/site/frame";

export const Route = createFileRoute("/enter")({ component: Enter });

function Enter() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [brand, setBrand] = useState("");
  const [mode, setMode] = useState<"signup" | "login">("signup");
  const [message, setMessage] = useState("");
  const [keys, setKeys] = useState<{ widget_key?: string; supervisor_key?: string; tenant_id?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const response = await fetch(mode === "signup" ? "/signup" : "/login", {
      method: "POST",
      headers: { "content-type": "application/json", accept: "application/json" },
      body: JSON.stringify({ email, password, brand }),
    });
    const body = (await response.json()) as {
      detail?: string;
      tenant_id?: string;
      widget_key?: string;
      supervisor_key?: string;
    };
    setBusy(false);
    if (!response.ok) {
      setKeys(null);
      setMessage(body.detail || "That did not work.");
      return;
    }
    setKeys(body);
    setMessage(mode === "signup" ? "Brand created. Keys are shown once." : "Signed in.");
  }

  return (
    <SiteFrame>
      <main className="mx-auto max-w-lg px-4 py-16">
        <p className="font-mono text-xs uppercase tracking-widest text-muted">Owner</p>
        <h1 className="mt-3 font-display text-4xl leading-none">Open a brand on the D2C agent.</h1>
        <p className="mt-4 text-muted">
          Signup creates the tenant on the agent, a widget test key, and a supervisor test key. The cookie is the brand for the desk, the sandbox, and the widget.
        </p>
        <div className="mt-6 flex gap-2">
          <button type="button" className={`h-11 rounded-md px-4 text-sm ${mode === "signup" ? "bg-accent text-ink" : "border border-line"}`} onClick={() => setMode("signup")}>
            Create brand
          </button>
          <button type="button" className={`h-11 rounded-md px-4 text-sm ${mode === "login" ? "bg-accent text-ink" : "border border-line"}`} onClick={() => setMode("login")}>
            Sign in
          </button>
        </div>
        <form className="mt-6 space-y-3" onSubmit={(event) => void submit(event)}>
          {mode === "signup" && (
            <input className="h-11 w-full rounded-md border border-line bg-elev px-3" placeholder="Brand name" value={brand} onChange={(event) => setBrand(event.target.value)} />
          )}
          <input className="h-11 w-full rounded-md border border-line bg-elev px-3" placeholder="Email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
          <input className="h-11 w-full rounded-md border border-line bg-elev px-3" placeholder="Password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} required minLength={8} />
          <button type="submit" disabled={busy} className="h-11 w-full rounded-md bg-accent font-medium text-ink disabled:opacity-50">
            {busy ? "Working" : mode === "signup" ? "Create" : "Sign in"}
          </button>
        </form>
        {message && <p className="mt-4 text-sm">{message}</p>}
        {keys?.widget_key && (
          <pre className="mt-4 overflow-x-auto rounded-md border border-line bg-elev p-4 font-mono text-xs text-muted">
{`tenant ${keys.tenant_id}
widget     ${keys.widget_key}
supervisor ${keys.supervisor_key}`}
          </pre>
        )}
        <Link to="/console" className="mt-6 inline-flex h-11 items-center text-sm underline">
          Open your support desk
        </Link>
      </main>
    </SiteFrame>
  );
}
