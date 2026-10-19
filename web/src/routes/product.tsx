import type { ReactNode } from "react";
import { createFileRoute, Link } from "@tanstack/react-router";
import { SiteFrame } from "@/components/site/frame";

export const Route = createFileRoute("/product")({ component: Product });

function Product() {
  return (
    <SiteFrame>
      <main>
        <section className="border-b border-line">
          <div className="mx-auto max-w-6xl px-4 py-16 md:py-20">
            <p className="font-mono text-xs uppercase tracking-widest text-muted">Product</p>
            <h1 className="mt-4 max-w-3xl font-display text-5xl leading-none md:text-6xl">
              A helpdesk that knows when to stop.
            </h1>
            <p className="mt-6 max-w-2xl text-lg text-muted">
              A persistent inbox, answers grounded in uploaded policies, and human review for support actions. New brands start with real payments disabled.
            </p>
          </div>
        </section>

        <Band
          eyebrow="Desk"
          title="Customer chat and human support share a case."
          body="Storefront chat creates a case in your brand inbox. Operators can take over, reply directly to the customer and resolve the conversation. WhatsApp and voice are not available in this pilot. The example cases alongside this text are illustrative."
          cta="Open the inbox"
          to="/console/inbox"
          aside={
            <ul className="divide-y divide-line border-y border-line text-sm">
              <li className="flex justify-between py-3"><span>NL-18420 · damaged tee</span><span className="text-muted">Waiting</span></li>
              <li className="flex justify-between py-3"><span>NL-18455 · ₹2,500</span><span className="text-accent">Approval</span></li>
              <li className="flex justify-between py-3"><span>NL-18302 · where is it</span><span className="text-muted">Resolved</span></li>
              <li className="flex justify-between py-3"><span>NL-18390 · size exchange</span><span className="text-accent">Open</span></li>
            </ul>
          }
        />

        <Band
          flip
          eyebrow="Agent"
          title="The reply names the clause, or it asks for what is missing."
          body="Published policy is the only source. A damaged return without photos stays with the customer. A cancel still in the warehouse is cancelled. A question the snapshot does not cover is refused, not invented. Automations are those paths, and you can turn one off without deleting the week’s runs."
          cta="Read policies"
          to="/console/policies"
          aside={
            <div className="rounded-lg border border-line bg-bg p-4 text-sm">
              <p className="font-mono text-xs text-accent">Clause 8.1.2</p>
              <p className="mt-3">Damage at delivery can be returned when the customer sends images of the tear and the pack. No photos, no refund path.</p>
              <p className="mt-4 font-mono text-xs text-muted">Northline · published snapshot</p>
            </div>
          }
        />

        <Band
          eyebrow="Hold"
          title="Money has a line. The model does not cross it."
          body="Northline holds at ₹2,000. Mira Pantry holds at ₹500. Under the line, Archal can queue a refund to the original method and still not call Stripe in this workspace. Over the line, the case sits in Approvals until a person approves the hold or rejects it. A second decision is refused."
          cta="Open approvals"
          to="/console/approvals"
          aside={
            <div className="rounded-lg border border-line p-4">
              <p className="font-mono text-xs text-muted">Decision</p>
              <p className="mt-3 text-2xl">₹2,500 held</p>
              <p className="mt-2 text-sm text-muted">Pilot actions use mock providers. A real payment requires separate merchant validation and administrator enablement.</p>
            </div>
          }
        />

        <Band
          flip
          eyebrow="Listen"
          title="Inspect response checks and operator outcomes."
          body="The quality view reports deterministic checks for citations, refund claims and persisted outcomes. These checks do not measure semantic correctness or tone. Human review and an evaluated dataset are required before trusting model quality."
          cta="Open quality"
          to="/console/quality"
          aside={
            <div className="grid grid-cols-3 gap-2">
              {[
                ["Citation", "Check"],
                ["Claims", "Check"],
                ["Outcome", "Check"],
              ].map(([k, v]) => (
                <div key={k} className="rounded-lg border border-line px-3 py-4">
                  <p className="font-mono text-xs text-muted">{k}</p>
                  <p className="mt-2 font-display text-3xl leading-none">{v}</p>
                </div>
              ))}
            </div>
          }
        />

        <section className="border-t border-line">
          <div className="mx-auto max-w-6xl px-4 py-16">
            <h2 className="font-display text-4xl leading-none">Then the control plane</h2>
            <p className="mt-4 max-w-2xl text-muted">
              Sandbox, knowledge upload, connection last-fours, and the widget install stay behind the desk. They are how a brand is allowed to go live. They are not the morning an operator spends in the queue.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row">
              <Link to="/console" className="inline-flex h-11 items-center justify-center rounded-md bg-accent px-4 text-sm font-medium text-ink">
                Open the console
              </Link>
              <Link to="/security" className="inline-flex h-11 items-center justify-center rounded-md border border-line px-4 text-sm">
                Read the isolation notes
              </Link>
            </div>
          </div>
        </section>
      </main>
    </SiteFrame>
  );
}

function Band({
  eyebrow,
  title,
  body,
  cta,
  to,
  aside,
  flip,
}: {
  eyebrow: string;
  title: string;
  body: string;
  cta: string;
  to: "/console/inbox" | "/console/policies" | "/console/approvals" | "/console/quality";
  aside: ReactNode;
  flip?: boolean;
}) {
  return (
    <section className="border-b border-line">
      <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 md:grid-cols-2">
        <div className={flip ? "md:order-2" : undefined}>
          <p className="font-mono text-xs uppercase tracking-widest text-accent">{eyebrow}</p>
          <h2 className="mt-3 font-display text-4xl leading-none">{title}</h2>
          <p className="mt-4 text-muted">{body}</p>
          <Link to={to} className="mt-6 inline-flex h-11 items-center text-sm underline decoration-line underline-offset-4">
            {cta}
          </Link>
        </div>
        <div>{aside}</div>
      </div>
    </section>
  );
}
