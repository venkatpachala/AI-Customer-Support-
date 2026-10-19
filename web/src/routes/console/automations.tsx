import { createFileRoute } from "@tanstack/react-router";
import { useState } from "react";
import { useBrand } from "@/components/console/brand";
import { Empty, LoadingLines } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { listAutomations, toggleAutomation } from "@/lib/ops";

export const Route = createFileRoute("/console/automations")({ component: Automations });

function Automations() {
  const { brandId } = useBrand();
  const { data, error, loading, reload } = useLoad(() => listAutomations({ data: { brandId } }), [brandId]);
  const [busyId, setBusyId] = useState("");
  const [note, setNote] = useState("");

  async function toggle(id: string) {
    setBusyId(id);
    setNote("");
    try {
      const result = await toggleAutomation({ data: { id } });
      if (!result.ok) setNote(result.error);
      else reload();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "The switch did not save.");
    } finally {
      setBusyId("");
    }
  }

  return (
    <div>
      <h1 className="font-display text-4xl leading-none">Automations</h1>
      <p className="mt-3 max-w-xl text-sm text-muted">
        Rules the agent is allowed to run. Turning one off stops that path. It does not delete the history.
      </p>
      {note ? <p className="mt-4 text-sm text-muted">{note}</p> : null}
      {loading && !data ? <div className="mt-6"><LoadingLines /></div> : null}
      {error ? (
        <div className="mt-6">
          <Empty title="Automations did not load." body={error} />
        </div>
      ) : null}
      <ul className="mt-6 divide-y divide-line overflow-hidden rounded-lg border border-line">
        {(data ?? []).map((row) => (
          <li key={row.id} className="flex flex-col gap-4 px-4 py-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-baseline gap-3">
                <h2 className="text-lg">{row.name}</h2>
                <span className="font-mono text-xs text-muted tabular-nums">{row.runs7d} runs / 7d</span>
              </div>
              <p className="mt-2 text-sm text-muted">When {row.triggerText.toLowerCase()}.</p>
              <p className="mt-1 text-sm">{row.actionText}</p>
            </div>
            <button
              type="button"
              role="switch"
              aria-checked={row.enabled}
              disabled={busyId === row.id}
              onClick={() => void toggle(row.id)}
              className={
                row.enabled
                  ? "h-11 shrink-0 rounded-md bg-accent px-4 text-sm font-medium text-ink"
                  : "h-11 shrink-0 rounded-md border border-line px-4 text-sm text-muted"
              }
            >
              {row.enabled ? "On" : "Off"}
            </button>
          </li>
        ))}
      </ul>
      {!loading && !error && (data?.length ?? 0) === 0 ? (
        <div className="mt-6">
          <Empty title="No rules for this brand." body="Automations are published per brand, with the policy." />
        </div>
      ) : null}
    </div>
  );
}
