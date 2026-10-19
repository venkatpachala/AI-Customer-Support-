import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";

export const Route = createFileRoute("/console/install")({ component: Install });

type Me = {
  tenant_id: string;
  sandbox_passed_at?: string | null;
  killed?: boolean;
  live_enabled?: boolean;
};

async function postForm(path: string, fields: Record<string, string> = {}) {
  const body = new URLSearchParams(fields);
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" },
    body,
  });
  const payload = (await response.json().catch(() => ({}))) as { detail?: string; widget_key?: string; killed?: boolean; live_enabled?: boolean };
  if (!response.ok) throw new Error(payload.detail || "The agent refused that action.");
  return payload;
}

function Install() {
  const [me, setMe] = useState<Me | null>(null);
  const [note, setNote] = useState("");
  const [password, setPassword] = useState("");
  const [revealed, setRevealed] = useState("");

  async function refresh() {
    const response = await fetch("/v1/me", { credentials: "include", headers: { accept: "application/json" } });
    if (!response.ok) {
      setMe(null);
      return;
    }
    setMe((await response.json()) as Me);
  }

  useEffect(() => {
    void refresh();
  }, []);

  const host = typeof window === "undefined" ? "" : window.location.origin;
  const snippet = me ? `<script src="${host}/widget.js?tenant=${encodeURIComponent(me.tenant_id)}"></script>` : "";

  return (
    <div className="max-w-2xl">
      <h1 className="text-2xl font-medium">Install</h1>
      <p className="mt-1 text-sm text-muted">
        Keys, the kill switch, and live tools go through the D2C agent. A new widget key is shown once. Refunds above the cap still wait.
      </p>
      {!me ? (
        <p className="mt-4 text-sm">
          <Link to="/enter" className="underline">Sign in</Link> to load this brand.
        </p>
      ) : (
        <dl className="mt-6 space-y-3 rounded-lg border border-line p-4 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Tenant</dt>
            <dd className="font-mono">{me.tenant_id}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Sandbox</dt>
            <dd>{me.sandbox_passed_at ? "passed" : "not passed"}</dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted">Live tools</dt>
            <dd>{me.live_enabled ? "enabled by an admin" : "off"}</dd>
          </div>
        </dl>
      )}

      <h2 className="mt-8 text-lg">Widget snippet</h2>
      <pre className="mt-2 overflow-x-auto rounded-lg border border-line bg-elev p-4 font-mono text-xs text-muted">{snippet || "Sign in to copy the snippet."}</pre>
      {me && (
        <p className="mt-2 text-sm text-muted">
          Open <Link to="/w/$tenant" params={{ tenant: me.tenant_id }} className="underline">/w/{me.tenant_id}</Link>. The chat box sends no verified field.
        </p>
      )}

      <h2 className="mt-8 text-lg">Controls</h2>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <button
          type="button"
          className="h-11 rounded-md border border-line px-4 text-sm"
          onClick={() => {
            void postForm("/app/install/rotate-test-key")
              .then((payload) => {
                setRevealed(payload.widget_key || "");
                setNote("Previous test key revoked. Copy the new key now.");
              })
              .catch((error: unknown) => setNote(error instanceof Error ? error.message : "Rotate failed."));
          }}
        >
          Rotate test key
        </button>
        <button
          type="button"
          className="h-11 rounded-md border border-line px-4 text-sm"
          onClick={() => {
            void postForm("/app/install/kill")
              .then(async (payload) => {
                setNote(payload.killed ? "Brand chat is disabled." : "Brand chat is enabled.");
                await refresh();
              })
              .catch((error: unknown) => setNote(error instanceof Error ? error.message : "Kill switch failed."));
          }}
        >
          {me?.killed ? "Enable brand" : "Disable brand"}
        </button>
      </div>
      <form
        className="mt-4 flex flex-col gap-2 sm:flex-row"
        onSubmit={(event) => {
          event.preventDefault();
          void postForm("/app/install/live", { ops_password: password })
            .then(async () => {
              setPassword("");
              setNote("Live flag updated. Refunds above the cap still stop.");
              await refresh();
            })
            .catch((error: unknown) => setNote(error instanceof Error ? error.message : "Live tools were not enabled."));
        }}
      >
        <input
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          type="password"
          placeholder="Admin password"
          className="h-11 flex-1 rounded-md border border-line bg-elev px-3 text-sm"
        />
        <button type="submit" className="h-11 rounded-md border border-line px-4 text-sm">
          Toggle live tools
        </button>
      </form>
      {revealed && <pre className="mt-4 overflow-x-auto rounded-md border border-line bg-elev p-4 font-mono text-xs">{revealed}</pre>}
      {note && <p className="mt-3 text-sm text-muted">{note}</p>}
    </div>
  );
}
