import { createFileRoute, Link } from "@tanstack/react-router";
import { useBrand } from "@/components/console/brand";
import { Empty, LoadingLines, Panel } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { listQuality } from "@/lib/ops";

export const Route = createFileRoute("/console/quality")({ component: Quality });

function mean(values: number[]) {
  if (values.length === 0) return 0;
  return Math.round(values.reduce((sum, n) => sum + n, 0) / values.length);
}

function Quality() {
  const { brandId } = useBrand();
  const { data, error, loading } = useLoad(() => listQuality({ data: { brandId } }), [brandId]);
  const rows = data ?? [];
  const ai = rows.filter((row) => row.agentKind === "ai");
  const human = rows.filter((row) => row.agentKind === "human");

  return (
    <div>
      <h1 className="font-display text-4xl leading-none">Quality</h1>
      <p className="mt-3 max-w-xl text-sm text-muted">
        Checks on recorded conversations: citations present, refund claims consistent with execution, and outcome consistency. These checks do not grade tone or semantic answer correctness.
      </p>
      {loading && !data ? <div className="mt-6"><LoadingLines /></div> : null}
      {error ? (
        <div className="mt-6">
          <Empty title="Scores did not load." body={error} />
        </div>
      ) : null}
      {rows.length > 0 ? (
        <>
          <div className="mt-8 grid gap-3 sm:grid-cols-3">
            <Score k="Citations" ai={mean(ai.map((r) => r.policyScore))} human={mean(human.map((r) => r.policyScore))} />
            <Score k="Action claims" ai={mean(ai.map((r) => r.toneScore))} human={mean(human.map((r) => r.toneScore))} />
            <Score k="Outcome consistency" ai={mean(ai.map((r) => r.resolutionScore))} human={mean(human.map((r) => r.resolutionScore))} />
          </div>
          <ul className="mt-6 divide-y divide-line overflow-hidden rounded-lg border border-line">
            {rows.map((row) => {
              const low = Math.min(row.policyScore, row.toneScore, row.resolutionScore) < 75;
              return (
                <li key={row.id} className="px-4 py-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <Link to="/console/inbox/$id" params={{ id: row.conversationId }} className="hover:underline">
                      {row.subject}
                    </Link>
                    <span className="font-mono text-xs text-muted">{row.agentKind === "ai" ? "Archal" : "Floor"}</span>
                  </div>
                  <p className="mt-2 text-sm text-muted">{row.note}</p>
                  <p className={`mt-3 font-mono text-xs tabular-nums ${low ? "text-accent" : "text-muted"}`}>
                    Citations {row.policyScore} · Action claims {row.toneScore} · Outcome {row.resolutionScore}
                  </p>
                </li>
              );
            })}
          </ul>
        </>
      ) : null}
      {!loading && !error && rows.length === 0 ? (
        <div className="mt-6">
          <Empty title="No scores for this brand yet." body="Scored threads show up after a case is reviewed." />
        </div>
      ) : null}
    </div>
  );
}

function Score({ k, ai, human }: { k: string; ai: number; human: number }) {
  return (
    <Panel className="px-4 py-4">
      <p className="font-mono text-xs uppercase tracking-widest text-muted">{k}</p>
      <p className="mt-2 font-display text-4xl leading-none tabular-nums">{ai}</p>
      <p className="mt-2 text-sm text-muted">Archal · floor {human || "—"}</p>
    </Panel>
  );
}
