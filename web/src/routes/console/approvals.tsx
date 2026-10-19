import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useBrand } from "@/components/console/brand";
import { Button, Empty, LoadingLines } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { inr } from "@/lib/format";
import { decideRefund, listConversations } from "@/lib/ops";

export const Route = createFileRoute("/console/approvals")({ component: Approvals });

function Approvals() {
  const { brandId, brand } = useBrand();
  const { data, error, loading, reload } = useLoad(
    () => listConversations({ data: { brandId, status: "waiting_approval" } }),
    [brandId],
  );
  const [busyId, setBusyId] = useState("");
  const [note, setNote] = useState("");

  async function decide(id: string, action: "approve" | "reject") {
    setBusyId(id);
    setNote("");
    try {
      const result = await decideRefund({ data: { id, action } });
      if (!result.ok) setNote(result.error);
      else reload();
    } catch (err) {
      setNote(err instanceof Error ? err.message : "The decision did not save.");
    } finally {
      setBusyId("");
    }
  }

  return (
    <div>
      <h1 className="font-display text-4xl leading-none">Approvals</h1>
      <p className="mt-3 max-w-xl text-sm text-muted">
        {brand
          ? `Anything over ${inr(brand.refundCap)} waits here. Approval resumes a gated workflow. Payment status is confirmed by the backend.`
          : "Refunds above the cap wait here."}
      </p>
      {note ? <p className="mt-4 text-sm text-muted">{note}</p> : null}
      {loading && !data ? <div className="mt-6"><LoadingLines /></div> : null}
      {error ? (
        <div className="mt-6">
          <Empty title="Approvals did not load." body={error} />
        </div>
      ) : null}
      {!loading && !error && (data?.length ?? 0) === 0 ? (
        <div className="mt-6">
          <Empty title="Nothing is held." body="When a refund crosses the cap, it lands here instead of on a card." />
        </div>
      ) : null}
      <ul className="mt-6 space-y-3">
        {(data ?? []).map((row) => (
          <li key={row.id} className="rounded-lg border border-line bg-elev p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <Link to="/console/inbox/$id" params={{ id: row.id }} className="text-lg hover:underline">
                  {row.subject}
                </Link>
                <p className="mt-1 text-sm text-muted">{row.preview}</p>
                <p className="mt-2 font-mono text-xs text-muted">
                  {row.customerLabel} · {row.orderRef ?? "no order"} · {inr(row.amountInr)}
                </p>
              </div>
              <div className="flex gap-2">
                <Button type="button" disabled={busyId === row.id} onClick={() => void decide(row.id, "approve")}>
                  Approve hold
                </Button>
                <Button type="button" tone="ghost" disabled={busyId === row.id} onClick={() => void decide(row.id, "reject")}>
                  Reject
                </Button>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
