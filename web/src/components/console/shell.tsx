import { Link, useRouterState } from "@tanstack/react-router";
import type { ReactNode } from "react";
import { Mark } from "@/components/site/frame";
import { BrandProvider, useBrand } from "@/components/console/brand";
import { cn } from "@/lib/cn";
import { inr } from "@/lib/format";


const WORK = [
  { to: "/console", label: "Overview", exact: true },
  { to: "/console/inbox", label: "Inbox", exact: false },
  { to: "/console/approvals", label: "Approvals", exact: false },
  { to: "/console/quality", label: "Quality", exact: false },
  { to: "/console/policies", label: "Policies", exact: false },
  { to: "/console/automations", label: "Automations", exact: false },
] as const;

const SETUP = [
  { to: "/console/settings", label: "Brand settings", exact: false },
  { to: "/console/sandbox", label: "Sandbox", exact: false },
  { to: "/console/knowledge", label: "Knowledge", exact: false },
  { to: "/console/connections", label: "Connections", exact: false },
  { to: "/console/install", label: "Install", exact: false },
] as const;

export function ConsoleFrame({ children }: { children: ReactNode }) {
  return (
    <BrandProvider>
      <ConsoleChrome>{children}</ConsoleChrome>
    </BrandProvider>
  );
}

function NavLink({
  to,
  label,
  exact,
  path,
}: {
  to: string;
  label: string;
  exact: boolean;
  path: string;
}) {
  const on = exact ? path === to : path.startsWith(to);
  return (
    <Link
      to={to}
      className={cn(
        "flex h-11 shrink-0 items-center rounded-md px-3 text-sm text-muted",
        on && "bg-surface text-fg",
      )}
    >
      {label}
    </Link>
  );
}

function ConsoleChrome({ children }: { children: ReactNode }) {
  const path = useRouterState({ select: (s) => s.location.pathname });
  const { brand, brands, brandId, setBrandId, error } = useBrand();

  return (
    <div className="min-h-screen bg-bg text-fg">
      <div className="flex min-h-screen flex-col md:flex-row">
        <aside className="border-b border-line md:w-56 md:shrink-0 md:border-b-0 md:border-r">
          <div className="flex items-center justify-between px-4 py-4">
            <Link to="/">
              <Mark />
            </Link>
            <span className="font-mono text-xs text-muted">Desk</span>
          </div>
          <div className="px-4 pb-3">
            <label className="text-xs text-muted" htmlFor="brand">
              Brand
            </label>
            <select
              id="brand"
              className="mt-1 h-11 w-full rounded-md border border-line bg-elev px-2 text-sm"
              value={brands.some((row) => row.id === brandId) ? brandId : (brand?.id ?? "")}
              onChange={(event) => setBrandId(event.target.value)}
            >
              {brands.length === 0 ? <option value="">Sign in to select a brand</option> : null}
              {brands.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.name}
                </option>
              ))}
            </select>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-3 pb-3 md:flex-col md:overflow-visible">
            {WORK.map((item) => (
              <NavLink key={item.to} {...item} path={path} />
            ))}
            <p className="hidden px-3 pt-4 pb-1 font-mono text-xs uppercase tracking-widest text-faint md:block">
              Setup
            </p>
            {SETUP.map((item) => (
              <NavLink key={item.to} {...item} path={path} />
            ))}
          </nav>
        </aside>
        <div className="min-w-0 flex-1">
          <div className="flex h-12 items-center justify-between gap-3 border-b border-line px-4">
            <p className="truncate font-mono text-xs text-muted">
              {brand ? `${brand.name} · ${brand.segment} · cap ${inr(brand.refundCap)}` : "Loading the desk"}
            </p>
            <p className="shrink-0 font-mono text-xs text-muted">Supervised support</p>
          </div>
          <div className="p-4 md:p-6">
            {error ? <p className="mb-4 text-sm text-accent">{error}</p> : null}
            {children}
          </div>
        </div>
      </div>
    </div>
  );
}
