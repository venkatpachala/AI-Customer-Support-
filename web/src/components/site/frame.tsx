import type { ReactNode } from "react";
import { Link, useRouterState } from "@tanstack/react-router";
import { Menu, X } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";

const LINKS = [
  { to: "/product", label: "Product" },
  { to: "/pricing", label: "Pricing" },
  { to: "/security", label: "Security" },
  { to: "/docs", label: "Docs" },
] as const;

export function Mark({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <span className="grid h-6 w-6 place-items-center rounded-sm bg-accent text-ink">
        <span className="font-mono text-xs font-medium">A</span>
      </span>
      <span className="font-medium tracking-wide">Archal</span>
    </span>
  );
}

export function SiteFrame({ children }: { children: ReactNode }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen bg-bg text-fg">
      <header className="sticky top-0 z-20 border-b border-line bg-bg/90 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4">
          <Link to="/" className="text-fg" onClick={() => setOpen(false)}>
            <Mark />
          </Link>
          <nav className="hidden items-center gap-6 md:flex">
            {LINKS.map((l) => (
              <Link
                key={l.to}
                to={l.to}
                className={cn(
                  "text-sm text-muted hover:text-fg",
                  path === l.to && "text-fg",
                )}
              >
                {l.label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            <Link
              to="/console"
              className="hidden h-9 items-center rounded-md bg-accent px-3 text-sm font-medium text-ink md:inline-flex"
            >
              Open console
            </Link>
            <button
              type="button"
              className="grid h-11 w-11 place-items-center rounded-md border border-line md:hidden"
              aria-label={open ? "Close menu" : "Open menu"}
              onClick={() => setOpen((v) => !v)}
            >
              {open ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </div>
        {open && (
          <div className="border-t border-line px-4 py-3 md:hidden">
            <div className="flex flex-col">
              {LINKS.map((l) => (
                <Link
                  key={l.to}
                  to={l.to}
                  className="flex h-11 items-center text-sm"
                  onClick={() => setOpen(false)}
                >
                  {l.label}
                </Link>
              ))}
              <Link
                to="/console"
                className="mt-2 flex h-11 items-center justify-center rounded-md bg-accent text-sm font-medium text-ink"
                onClick={() => setOpen(false)}
              >
                Open console
              </Link>
            </div>
          </div>
        )}
      </header>
      {children}
      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-10 md:flex-row md:justify-between">
          <div>
            <Mark />
            <p className="mt-3 max-w-sm text-sm text-muted">
              The customer operations system for D2C. The agent cites the clause. Refunds above your cap wait.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-x-10 gap-y-2 text-sm text-muted">
            <Link to="/product" className="hover:text-fg">Product</Link>
            <Link to="/pricing" className="hover:text-fg">Pricing</Link>
            <Link to="/security" className="hover:text-fg">Security</Link>
            <Link to="/architecture" className="hover:text-fg">Architecture</Link>
            <Link to="/docs" className="hover:text-fg">Docs</Link>
            <Link to="/status" className="hover:text-fg">Status</Link>
            <Link to="/terms" className="hover:text-fg">Terms</Link>
            <Link to="/privacy" className="hover:text-fg">Privacy</Link>
            <Link to="/w/$tenant" params={{ tenant: "northline" }} className="hover:text-fg">
              Sample widget
            </Link>
            <Link to="/enter" className="hover:text-fg">Create a brand</Link>
            <Link to="/support" className="hover:text-fg">Support</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}

export function Page({
  eyebrow,
  title,
  lede,
  children,
}: {
  eyebrow: string;
  title: string;
  lede: string;
  children: ReactNode;
}) {
  return (
    <SiteFrame>
      <main className="mx-auto max-w-6xl px-4 py-12 md:py-16">
        <p className="font-mono text-xs uppercase tracking-widest text-muted">{eyebrow}</p>
        <h1 className="mt-3 max-w-3xl text-4xl font-medium leading-tight md:text-5xl">{title}</h1>
        <p className="mt-4 max-w-2xl text-lg text-muted">{lede}</p>
        <div className="mt-12">{children}</div>
      </main>
    </SiteFrame>
  );
}
