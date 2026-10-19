import { createFileRoute, Link } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { useBrand } from "@/components/console/brand";
import { Empty, LoadingLines, Panel, StatusPill } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { intentLabel, inr } from "@/lib/format";
import { getOverview } from "@/lib/ops";

export const Route = createFileRoute("/console/")({ component: Overview });

function Overview() {
  const { brandId, brand } = useBrand();
  const { data, error, loading } = useLoad(() => getOverview({ data: { brandId } }), [brandId]);
  const [chartReady, setChartReady] = useState(false);
  useEffect(() => setChartReady(true), []);

  if (loading && !data) return <LoadingLines />;
  if (error) return <Empty title="The overview did not load." body={error} />;
  if (!data) return null;

  const maxIntent = Math.max(1, ...data.intents.map((row) => row.n));

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="font-mono text-xs uppercase tracking-widest text-muted">Recent cases</p>
          <h1 className="mt-2 font-display text-4xl leading-none">{brand?.name ?? "Desk"}</h1>
          <p className="mt-3 max-w-xl text-sm text-muted">
            What is open, what Archal already closed, and what is waiting because it moves money.
          </p>
        </div>
        <Link
          to="/console/inbox"
          className="inline-flex h-11 items-center rounded-md bg-accent px-4 text-sm font-medium text-ink"
        >
          Open inbox
        </Link>
      </div>

      <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat k="Needs a person" v={String(data.open)} d="Open, waiting, or held" />
        <Stat k="Resolved by Archal" v={String(data.aiResolved)} d="Completed AI workflows" />
        <Stat k="Above the cap" v={String(data.held)} d={brand ? `Hold line ${inr(brand.refundCap)}` : "Held"} />
        <Stat k="Cases in view" v={String(data.volume.reduce((total, day) => total + day.inbound, 0))} d="Most recent 100 cases" />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-5">
        <Panel className="p-4 lg:col-span-3">
          <div className="flex items-baseline justify-between gap-3">
            <h2 className="text-lg">Fourteen days</h2>
            <p className="font-mono text-xs text-muted">Cases updated and AI workflows completed</p>
          </div>
          <div className="mt-4 h-44">
            {chartReady ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.volume} barGap={2}>
                  <XAxis dataKey="day" hide />
                  <Tooltip
                    cursor={{ fill: "var(--color-surface)" }}
                    contentStyle={{
                      background: "var(--color-elev)",
                      border: "1px solid var(--color-line)",
                      borderRadius: 8,
                      color: "var(--color-fg)",
                      fontSize: 12,
                    }}
                    labelFormatter={(label) => String(label).slice(5)}
                  />
                  <Bar dataKey="inbound" fill="var(--color-line)" radius={[2, 2, 0, 0]} />
                  <Bar dataKey="resolvedByAi" fill="var(--color-accent)" radius={[2, 2, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : null}
          </div>
          <div className="mt-2 flex gap-4 font-mono text-xs text-muted">
            <span className="inline-flex items-center gap-2">
              <i className="inline-block h-2 w-2 bg-line" /> Inbound
            </span>
            <span className="inline-flex items-center gap-2">
              <i className="inline-block h-2 w-2 bg-accent" /> Resolved by Archal
            </span>
          </div>
        </Panel>
        <Panel className="p-4 lg:col-span-2">
          <h2 className="text-lg">By intent</h2>
          <ul className="mt-4 space-y-3">
            {data.intents.length === 0 ? <li className="text-sm text-muted">No cases for this brand.</li> : null}
            {data.intents.map((row) => (
              <li key={row.intent}>
                <div className="flex justify-between text-sm">
                  <span className="capitalize">{intentLabel(row.intent)}</span>
                  <span className="font-mono text-muted tabular-nums">{row.n}</span>
                </div>
                <div className="mt-1 h-1.5 rounded-sm bg-surface">
                  <div
                    className="h-1.5 rounded-sm bg-accent"
                    style={{ width: `${Math.round((row.n / maxIntent) * 100)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <div className="mt-6">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg">Queue</h2>
          <Link to="/console/approvals" className="text-sm text-muted hover:text-fg">
            Approvals
          </Link>
        </div>
        {data.queue.length === 0 ? (
          <div className="mt-3">
            <Empty title="Nothing is waiting." body="Archal has no open, held, or customer-blocked cases for this brand." />
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-line overflow-hidden rounded-lg border border-line">
            {data.queue.map((row) => (
              <li key={row.id}>
                <Link
                  to="/console/inbox/$id"
                  params={{ id: row.id }}
                  className="flex flex-col gap-2 px-4 py-4 hover:bg-elev sm:flex-row sm:items-center sm:justify-between"
                >
                  <div className="min-w-0">
                    <p className="truncate">{row.subject}</p>
                    <p className="mt-1 font-mono text-xs text-muted">
                      {row.customerLabel} · {row.channel} · {row.orderRef ?? "no order"}
                    </p>
                  </div>
                  <StatusPill status={row.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function Stat({ k, v, d }: { k: string; v: string; d: string }) {
  return (
    <div className="rounded-lg border border-line bg-elev px-4 py-4">
      <p className="font-mono text-xs uppercase tracking-widest text-muted">{k}</p>
      <p className="mt-2 font-display text-4xl leading-none tabular-nums">{v}</p>
      <p className="mt-2 text-sm text-muted">{d}</p>
    </div>
  );
}
