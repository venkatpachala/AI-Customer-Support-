import { createFileRoute, Link } from "@tanstack/react-router";
import { useState } from "react";
import { useBrand } from "@/components/console/brand";
import { Empty, LoadingLines, StatusPill } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { intentLabel, inr, whenLabel } from "@/lib/format";
import { listConversations } from "@/lib/ops";

export const Route = createFileRoute("/console/inbox/")({ component: Inbox });

const FILTERS = [
  { id: "all", label: "All" },
  { id: "open", label: "Open" },
  { id: "waiting_customer", label: "Waiting" },
  { id: "waiting_approval", label: "Approval" },
  { id: "ai_resolved", label: "Resolved" },
] as const;

function Inbox() {
  const { brandId } = useBrand();
  const { data, error, loading } = useLoad(() => listConversations({ data: { brandId } }), [brandId]);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]["id"]>("all");

  const rows = (data ?? []).filter((row) => (filter === "all" ? true : row.status === filter));

  return (
    <div>
      <h1 className="font-display text-4xl leading-none">Inbox</h1>
      <p className="mt-3 max-w-xl text-sm text-muted">
        Chat, WhatsApp, email, and voice for this brand. Another brand’s threads stay on their own desk.
      </p>
      <div className="mt-6 flex gap-2 overflow-x-auto pb-1">
        {FILTERS.map((item) => {
          const on = filter === item.id;
          return (
            <button
              key={item.id}
              type="button"
              aria-pressed={on}
              onClick={() => setFilter(item.id)}
              className={
                on
                  ? "h-11 shrink-0 rounded-md bg-accent px-3 text-sm font-medium text-ink"
                  : "h-11 shrink-0 rounded-md border border-line px-3 text-sm text-muted"
              }
            >
              {item.label}
            </button>
          );
        })}
      </div>
      {loading && !data ? (
        <div className="mt-6">
          <LoadingLines />
        </div>
      ) : null}
      {error ? (
        <div className="mt-6">
          <Empty title="The inbox did not load." body={error} />
        </div>
      ) : null}
      {!loading && !error && rows.length === 0 ? (
        <div className="mt-6">
          <Empty
            title="No threads in this view."
            body="Switch the filter, or change the brand. The other brand’s cases are not here."
          />
        </div>
      ) : null}
      {rows.length > 0 ? (
        <ul className="mt-4 divide-y divide-line overflow-hidden rounded-lg border border-line">
          {rows.map((row) => (
            <li key={row.id}>
              <Link
                to="/console/inbox/$id"
                params={{ id: row.id }}
                className="grid gap-2 px-4 py-4 hover:bg-elev md:grid-cols-12 md:items-center"
              >
                <div className="min-w-0 md:col-span-6">
                  <p className="truncate">{row.subject}</p>
                  <p className="mt-1 truncate text-sm text-muted">{row.preview}</p>
                </div>
                <p className="font-mono text-xs text-muted md:col-span-3">
                  {row.customerLabel} · {row.channel}
                  <span className="hidden md:inline"> · {intentLabel(row.intent)}</span>
                </p>
                <p className="font-mono text-xs text-faint md:col-span-2">
                  {row.amountInr != null ? inr(row.amountInr) : whenLabel(row.updatedAt)}
                </p>
                <div className="md:col-span-1 md:justify-self-end">
                  <StatusPill status={row.status} />
                </div>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
