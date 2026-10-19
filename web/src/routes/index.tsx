import { createFileRoute, Link } from "@tanstack/react-router";
import { SiteFrame } from "@/components/site/frame";

export const Route = createFileRoute("/")({ component: Home });

const SURFACES = [
  {
    n: "01",
    t: "Desk",
    d: "A customer chat widget and operator inbox with tenant-scoped cases, replies, and approvals.",
    to: "/console/inbox" as const,
    cta: "Open the inbox",
  },
  {
    n: "02",
    t: "Agent",
    d: "Archal answers from the published clause, asks for the photo it does not have, and refuses what the policy does not cover.",
    to: "/console/policies" as const,
    cta: "Read the clauses",
  },
  {
    n: "03",
    t: "Hold",
    d: "A refund above your cap waits for a person. Approve means held. It does not mean charged. Stripe stays off until you say otherwise.",
    to: "/console/approvals" as const,
    cta: "See the hold queue",
  },
  {
    n: "04",
    t: "Listen",
    d: "Every scored thread is graded on policy, tone, and whether it actually closed. The misses stay on the page.",
    to: "/console/quality" as const,
    cta: "Open quality",
  },
];

function Home() {
  return (
    <SiteFrame>
      <main>
        <section className="relative overflow-hidden border-b border-line">
          <div className="grid-fade pointer-events-none absolute inset-0" />
          <div className="relative mx-auto grid max-w-6xl items-center gap-12 px-4 py-16 md:grid-cols-12 md:py-24">
            <div className="md:col-span-7">
              <p className="font-mono text-xs uppercase tracking-widest text-accent">Customer operations for D2C</p>
              <h1 className="mt-4 font-display text-5xl leading-none md:text-6xl">
                The desk that resolves. The hold that stops the refund.
              </h1>
              <p className="mt-6 max-w-xl text-lg text-muted">
                Archal connects your policy documents, customer chat, and support desk. Review requests with their evidence and history. Live financial actions require separate integration validation.
              </p>
              <div className="mt-8 flex flex-col gap-3 sm:flex-row">
                <Link
                  to="/console/inbox"
                  className="inline-flex h-12 items-center justify-center rounded-md bg-accent px-5 font-medium text-ink transition-transform duration-150 ease-out active:scale-[0.96]"
                >
                  Open the desk
                </Link>
                <Link
                  to="/pricing"
                  className="inline-flex h-12 items-center justify-center rounded-md border border-line px-5 text-fg"
                >
                  See pricing
                </Link>
              </div>
            </div>
            <div className="md:col-span-5">
              <DeskCard />
            </div>
          </div>
        </section>

        <section className="border-b border-line">
          <div className="mx-auto grid max-w-6xl sm:grid-cols-3">
            <Metric k="Knowledge" v="Your policies" d="Upload text PDFs and reference their sources in chat." />
            <Metric k="Human review" v="In the loop" d="Take over a case and reply directly to the customer." />
            <Metric k="Financial actions" v="Gated" d="New brands start with transactional automations off." />
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16 md:py-20">
          <div className="max-w-2xl">
            <p className="font-mono text-xs uppercase tracking-widest text-muted">The system</p>
            <h2 className="mt-3 font-display text-4xl leading-none md:text-5xl">Four surfaces. One brand at a time.</h2>
          </div>
          <div className="mt-10 border-t border-line">
            {SURFACES.map((item) => (
              <article key={item.n} className="grid gap-4 border-b border-line py-8 md:grid-cols-12 md:items-center">
                <p className="font-mono text-sm text-accent md:col-span-1">{item.n}</p>
                <h3 className="font-display text-3xl md:col-span-3">{item.t}</h3>
                <p className="text-muted md:col-span-6">{item.d}</p>
                <Link to={item.to} className="text-sm text-fg underline decoration-line underline-offset-4 md:col-span-2">
                  {item.cta}
                </Link>
              </article>
            ))}
          </div>
        </section>

        <section className="border-y border-line bg-elev">
          <div className="mx-auto grid max-w-6xl gap-10 px-4 py-16 md:grid-cols-2 md:py-20">
            <div>
              <p className="font-mono text-xs uppercase tracking-widest text-muted">What it will not say</p>
              <h2 className="mt-3 font-display text-4xl leading-none">A refund is not done because the model is confident.</h2>
            </div>
            <ul className="divide-y divide-line border-y border-line">
              <Promise t="Citations or silence" d="If the clause is not in that brand’s snapshot, the reply says it does not know." />
              <Promise t="Proof before a damaged return" d="No photos, no refund path. The case waits on the customer." />
              <Promise t="The brand cannot be switched in the body" d="A forged tenant in the JSON is rejected. Retrieval stays inside the session brand." />
              <Promise t="Stripe is a later door" d="This workspace never charges a card. Approve means the hold stands." />
            </ul>
          </div>
        </section>

        <section className="mx-auto max-w-6xl px-4 py-16 md:py-20">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <h2 className="font-display text-4xl leading-none">Channels operators already live in</h2>
            <Link to="/product" className="text-sm text-muted hover:text-fg">
              Product detail
            </Link>
          </div>
          <div className="mt-8 grid gap-px overflow-hidden rounded-lg border border-line bg-line sm:grid-cols-4">
            {[
              ["WhatsApp", "Not available in this release."],
              ["Email", "Verification emails require configured SMTP."],
              ["Chat", "The widget on the storefront."],
              ["Voice", "Experimental; outside the supported chat pilot."],
            ].map(([title, copy]) => (
              <div key={title} className="bg-bg px-4 py-6">
                <h3 className="text-lg">{title}</h3>
                <p className="mt-2 text-sm text-muted">{copy}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="border-t border-line">
          <div className="mx-auto flex max-w-6xl flex-col items-start gap-6 px-4 py-16 md:flex-row md:items-end md:justify-between">
            <div>
              <h2 className="font-display text-4xl leading-none md:text-5xl">Put a real morning on the desk.</h2>
              <p className="mt-4 max-w-lg text-muted">
                Northline and Mira Pantry are loaded. Switch brands. Approve a hold. Turn a rule off. Nothing here charges a card.
              </p>
            </div>
            <Link
              to="/console"
              className="inline-flex h-12 items-center rounded-md bg-accent px-5 font-medium text-ink"
            >
              Enter the console
            </Link>
          </div>
        </section>
      </main>
    </SiteFrame>
  );
}

function Metric({ k, v, d }: { k: string; v: string; d: string }) {
  return (
    <div className="border-b border-line px-4 py-8 last:border-b-0 sm:border-b-0 sm:border-r sm:last:border-r-0">
      <p className="font-mono text-xs uppercase tracking-widest text-muted">{k}</p>
      <p className="mt-3 font-display text-4xl leading-none">{v}</p>
      <p className="mt-3 text-sm text-muted">{d}</p>
    </div>
  );
}

function Promise({ t, d }: { t: string; d: string }) {
  return (
    <li className="py-4">
      <p className="font-medium">{t}</p>
      <p className="mt-1 text-sm text-muted">{d}</p>
    </li>
  );
}

function DeskCard() {
  return (
    <div className="rounded-lg border border-line bg-elev">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <span className="font-mono text-xs text-muted">Illustrative inbox</span>
        <span className="rounded-sm border border-accent px-2 py-1 font-mono text-xs text-accent">Needs approval</span>
      </div>
      <div className="space-y-3 p-4">
        <div className="rounded-md border border-line bg-surface px-3 py-3 text-sm">
          <p className="font-mono text-xs text-muted">Example customer · chat · NL-18455</p>
          <p className="mt-2">Please refund ₹2,500. The jacket was stained on arrival.</p>
        </div>
        <div className="rounded-md border border-line bg-bg px-3 py-3 text-sm">
          <p className="font-mono text-xs text-muted">Archal</p>
          <p className="mt-2">This refund is above the ₹2,000 cap. I have held it. Stripe was not called.</p>
          <p className="mt-3 inline-flex rounded-sm border border-line px-2 py-1 font-mono text-xs text-accent">Clause 9.1</p>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div className="flex h-11 items-center justify-center rounded-md bg-accent text-sm font-medium text-ink">Approve hold</div>
          <div className="flex h-11 items-center justify-center rounded-md border border-line text-sm">Reject</div>
        </div>
      </div>
    </div>
  );
}
