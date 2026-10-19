import { createFileRoute, Link } from "@tanstack/react-router";
import { useBrand } from "@/components/console/brand";
import { Empty, LoadingLines } from "@/components/ops/ui";
import { useLoad } from "@/components/ops/use-load";
import { listPolicies } from "@/lib/ops";

export const Route = createFileRoute("/console/policies")({ component: Policies });

function Policies() {
  const { brandId, brand } = useBrand();
  const { data, error, loading } = useLoad(() => listPolicies({ data: { brandId } }), [brandId]);

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-4xl leading-none">Policies</h1>
          <p className="mt-3 max-w-xl text-sm text-muted">
            {brand ? `${brand.name} answers from the snapshots on the D2C agent.` : "Published clauses."} A missing clause is not invented.
          </p>
        </div>
        <Link to="/console/knowledge" className="text-sm text-muted hover:text-fg">
          Upload a snapshot
        </Link>
      </div>
      {loading && !data ? <div className="mt-6"><LoadingLines /></div> : null}
      {error ? (
        <div className="mt-6">
          <Empty title="Policies did not load." body={error} />
        </div>
      ) : null}
      <div className="mt-6 divide-y divide-line overflow-hidden rounded-lg border border-line">
        {(data ?? []).map((policy) => (
          <article key={policy.id} className="grid gap-2 px-4 py-5 md:grid-cols-4">
            <div>
              <p className="font-mono text-xs text-accent">{policy.clause}</p>
              <h2 className="mt-2 text-lg">{policy.title}</h2>
            </div>
            <p className="text-sm text-muted md:col-span-3">{policy.body}</p>
          </article>
        ))}
      </div>
      {!loading && !error && (data?.length ?? 0) === 0 ? (
        <div className="mt-6">
          <Empty title="No published clauses." body="This brand has nothing for Archal to cite." />
        </div>
      ) : null}
    </div>
  );
}
