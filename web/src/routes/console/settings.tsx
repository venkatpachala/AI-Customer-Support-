import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
export const Route = createFileRoute("/console/settings")({ component: Settings });
type Values = { brand_name: string; tone: string; support_email: string; auto_refund_max: number | string; manager_refund_max: number | string };
function Settings() {
  const [values, setValues] = useState<Values | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => { void fetch("/v1/desk/settings", { credentials: "include" }).then(async (response) => {
    if (!response.ok) throw new Error("Sign in to edit brand settings.");
    setValues(await response.json() as Values);
  }).catch((e: unknown) => setNote(e instanceof Error ? e.message : "Settings could not load.")); }, []);
  async function save() {
    setBusy(true); setNote("");
    try {
      const response = await fetch("/v1/desk/settings", { method: "PUT", credentials: "include",
        headers: { "content-type": "application/json" }, body: JSON.stringify(values) });
      const body = await response.json() as { detail?: unknown };
      if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : "Check the field values and retry.");
      setNote("Settings saved. New policy decisions use this version. Live tools require separate administrator enablement.");
    } catch (e) { setNote(e instanceof Error ? e.message : "Settings did not save."); }
    finally { setBusy(false); }
  }
  return <div className="max-w-xl"><h1 className="text-2xl font-medium">Brand settings</h1>
    <p className="mt-2 text-sm text-muted">Policy limits apply to future decisions. Changing a cap does not enable live payments or remove customer verification.</p>
    {values && <form className="mt-6 space-y-4" onSubmit={(e) => { e.preventDefault(); void save(); }}>
      {([ ["brand_name", "Brand name"], ["tone", "Response tone"], ["support_email", "Support email"],
           ["auto_refund_max", "Automatic refund cap in INR"], ["manager_refund_max", "Supervisor refund cap in INR"] ] as const).map(([key, label]) =>
        <label key={key} className="block text-sm">{label}<input value={values[key]}
          type={key.endsWith("max") ? "number" : key === "support_email" ? "email" : "text"} min="0" step="0.01"
          onChange={(e) => setValues({ ...values, [key]: e.target.value })}
          className="mt-1 h-11 w-full rounded border border-line bg-elev px-3" /></label>)}
      <button disabled={busy} className="h-11 rounded bg-accent px-4 text-ink">{busy ? "Saving…" : "Save settings"}</button>
    </form>}{note && <p role="status" className="mt-4 text-sm">{note}</p>}
  </div>;
}
