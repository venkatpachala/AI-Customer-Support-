import { createFileRoute, Link } from "@tanstack/react-router";
import { SiteFrame } from "@/components/site/frame";

export const Route = createFileRoute("/pricing")({ component: Pricing });

const TIERS = [
  {
    name: "Desk",
    price: "Pilot",
    period: "invitation only",
    lead: "The queue, without the agent.",
    points: ["Storefront chat", "Brand owner access", "Cases, assignment, replies", "No policy agent"],
    cta: "Open the desk",
    to: "/console/inbox" as const,
    hot: false,
  },
  {
    name: "Resolve",
    price: "Pilot",
    period: "invitation only",
    lead: "The agent, the hold, and the score.",
    points: ["Everything in Desk", "Policy-cited replies", "Refund cap and approvals", "Deterministic response checks", "Operator handoff on the same case"],
    cta: "Use Resolve",
    to: "/console" as const,
    hot: true,
  },
  {
    name: "Platform",
    price: "Talk",
    period: "multi-brand",
    lead: "For a group that needs the gate.",
    points: ["More than one brand", "Sandbox before anything live", "Daily cap and kill switch", "A person on the rollout"],
    cta: "Read security",
    to: "/security" as const,
    hot: false,
  },
];

function Pricing() {
  return (
    <SiteFrame>
      <main className="mx-auto max-w-6xl px-4 py-16 md:py-20">
        <p className="font-mono text-xs uppercase tracking-widest text-muted">Pricing</p>
        <h1 className="mt-4 max-w-3xl font-display text-5xl leading-none">Start with a supervised pilot.</h1>
        <p className="mt-5 max-w-2xl text-lg text-muted">
          This release is an invited pilot. Paid plans and subscription billing are not available. Validate the support workflow with your own policies before a wider rollout.
        </p>
        <div className="mt-12 grid gap-4 lg:grid-cols-3">
          {TIERS.map((tier) => (
            <article
              key={tier.name}
              className={tier.hot ? "rounded-lg border border-accent bg-elev p-6" : "rounded-lg border border-line p-6"}
            >
              <p className="font-mono text-xs uppercase tracking-widest text-muted">{tier.name}</p>
              <p className="mt-4 font-display text-5xl leading-none">{tier.price}</p>
              <p className="mt-2 text-sm text-muted">{tier.period}</p>
              <p className="mt-4">{tier.lead}</p>
              <ul className="mt-6 space-y-2 text-sm text-muted">
                {tier.points.map((point) => (
                  <li key={point}>{point}</li>
                ))}
              </ul>
              <Link
                to={tier.to}
                className={
                  tier.hot
                    ? "mt-8 inline-flex h-11 items-center rounded-md bg-accent px-4 text-sm font-medium text-ink"
                    : "mt-8 inline-flex h-11 items-center rounded-md border border-line px-4 text-sm"
                }
              >
                {tier.cta}
              </Link>
            </article>
          ))}
        </div>
        <p className="mt-10 max-w-2xl text-sm text-muted">
          The backend encrypts saved Shopify and Stripe credentials. Connecting a provider does not enable real payments. WhatsApp and voice support are not available in this pilot.
        </p>
      </main>
    </SiteFrame>
  );
}
