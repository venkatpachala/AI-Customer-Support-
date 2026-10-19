import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
export const Route = createFileRoute("/console/knowledge")({ component: Knowledge });
type Doc = { id: string; filename: string; status: string; page_count: number; error?: string };
function Knowledge() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    const response = await fetch("/v1/knowledge", { credentials: "include" });
    const body = await response.json() as { documents?: Doc[]; detail?: string };
    if (!response.ok) throw new Error(body.detail || "Sign in to view knowledge.");
    setDocs((body.documents || []).filter((doc) => doc.status !== "deleted"));
  }
  useEffect(() => { void refresh().catch((e: unknown) => setError(e instanceof Error ? e.message : "Could not load documents.")); }, []);
  async function upload(file: File) {
    if (file.size > 8 * 1024 * 1024) { setError("Choose a PDF under 8 MB."); return; }
    setBusy(true); setError("");
    try {
      const data = new FormData(); data.set("file", file);
      const response = await fetch("/v1/knowledge", { method: "POST", credentials: "include", body: data, signal: AbortSignal.timeout(90000) });
      const body = await response.json() as { detail?: string };
      if (!response.ok) throw new Error(body.detail || "Upload failed.");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Upload failed."); }
    finally { setBusy(false); }
  }
  async function remove(id: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch(`/v1/knowledge/${encodeURIComponent(id)}`, { method: "DELETE", credentials: "include" });
      if (!response.ok) throw new Error("The document could not be removed.");
      await refresh();
    } catch (e) { setError(e instanceof Error ? e.message : "Delete failed."); }
    finally { setBusy(false); }
  }
  return <div>
    <h1 className="text-2xl font-medium">Knowledge</h1>
    <p className="mt-2 max-w-2xl text-sm text-muted">Text PDFs up to 8 MB and 200 pages. All ready documents form your brand's collection. Documents remain available after service restarts.</p>
    <label className="mt-6 inline-flex h-11 cursor-pointer items-center rounded-md bg-accent px-4 text-sm font-medium text-ink">
      {busy ? "Processing…" : "Upload PDF"}
      <input type="file" accept="application/pdf,.pdf" disabled={busy} className="sr-only" onChange={(e) => {
        const file = e.target.files?.[0]; e.target.value = ""; if (file) void upload(file);
      }} />
    </label>
    {error && <p role="alert" className="mt-3 text-sm">{error}</p>}
    <ul className="mt-6 divide-y divide-line rounded-lg border border-line">
      {!docs.length && <li className="px-4 py-6 text-sm text-muted">No documents yet.</li>}
      {docs.map((doc) => <li key={doc.id} className="flex items-start justify-between gap-4 px-4 py-4">
        <div><p>{doc.filename}</p><p className="mt-1 text-xs text-muted">{doc.status === "ingested" ? "Ready" : doc.status} · {doc.page_count} pages</p>
          {doc.error && <p className="mt-1 text-xs">{doc.error}</p>}</div>
        <button disabled={busy} onClick={() => void remove(doc.id)} className="h-10 rounded border border-line px-3 text-sm">Remove</button>
      </li>)}
    </ul>
  </div>;
}
