import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { SANDBOX_STEPS } from "@/lib/runtime";
import { useBrand } from "@/components/console/brand";

export const Route = createFileRoute("/console/sandbox")({ component: Sandbox });

type Row = { id: string; pass: boolean; notes: string[]; response: string };

function Sandbox() {
  useBrand();
  const [rows, setRows] = useState<Row[]>([]);
  const [busy, setBusy] = useState(false);
  const [summary, setSummary] = useState("");

  async function runAll() {
    setBusy(true);
    setSummary("");
    const response = await fetch("/v1/sandbox/run", {
      method: "POST",
      credentials: "include",
      headers: { accept: "application/json" },
    });
    const body = (await response.json().catch(() => ({}))) as {
      detail?: string;
      passed?: boolean;
      turns?: { message?: string; workflow_status?: string; citations?: string[]; missing_inputs?: string[] }[];
    };
    if (!response.ok) {
      setRows([]);
      setSummary(body.detail || "The agent refused the sandbox. Sign in on Enter first.");
      setBusy(false);
      return;
    }
    const next: Row[] = SANDBOX_STEPS.map((step, index) => {
      const turn = body.turns?.[index];
      const notes = [
        turn?.workflow_status ? `status ${turn.workflow_status}` : "no turn",
        ...(turn?.citations ?? []),
        ...(turn?.missing_inputs ?? []).map((item) => `missing ${item}`),
      ];
      const pass =
        (step.id === "S1" && (turn?.citations?.length ?? 0) > 0) ||
        (step.id === "S2" && (turn?.workflow_status === "waiting_customer" || (turn?.missing_inputs?.length ?? 0) > 0)) ||
        (step.id === "S3" && turn?.workflow_status === "waiting_approval");
      return { id: step.id, pass, notes, response: turn?.workflow_status || "no reply" };
    });
    setRows(next);
    setSummary(
      body.passed
        ? "Sandbox passed on the D2C agent. Live tools stay off until an admin enables this brand."
        : "Sandbox did not pass. The agent still holds refunds above the cap.",
    );
    setBusy(false);
  }

  return (
    <div>
      <h1 className="text-2xl font-medium">Sandbox</h1>
      <p className="mt-1 max-w-2xl text-sm text-muted">
        Three messages run on the D2C agent for the signed-in brand. A pass needs a citation, a photo ask, and a refund held above the cap. Stripe stays off.
      </p>
      <button
        type="button"
        disabled={busy}
        onClick={runAll}
        className="mt-6 h-11 rounded-md bg-accent px-4 text-sm font-medium text-ink disabled:opacity-50"
      >
        {busy ? "Running…" : "Run three messages"}
      </button>
      <ul className="mt-6 space-y-3">
        {SANDBOX_STEPS.map((step) => {
          const row = rows.find((r) => r.id === step.id);
          return (
            <li key={step.id} className="rounded-lg border border-line p-4">
              <div className="flex items-center justify-between gap-3">
                <p className="font-medium">{step.label}</p>
                <span className="font-mono text-xs text-muted">{row ? (row.pass ? "pass" : "fail") : step.id}</span>
              </div>
              <p className="mt-2 text-sm text-muted">{step.message}</p>
              <p className="mt-1 text-xs text-faint">{step.expect}</p>
              {row && <p className="mt-3 text-sm">{row.response}</p>}
              {row && row.notes.length > 0 && (
                <ul className="mt-2 text-sm text-muted">
                  {row.notes.map((n) => (
                    <li key={n}>{n}</li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
      {summary && <p className="mt-4 text-sm">{summary}</p>}
    </div>
  );
}
