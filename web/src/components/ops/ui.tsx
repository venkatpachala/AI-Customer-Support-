import type { ButtonHTMLAttributes, ReactNode } from "react";
import { cn } from "@/lib/cn";
import { STATUS_LABEL } from "@/lib/format";

export function StatusPill({ status }: { status: string }) {
  const hot = status === "waiting_approval" || status === "open";
  return (
    <span
      className={cn(
        "inline-flex h-6 items-center rounded-sm border px-2 font-mono text-xs whitespace-nowrap",
        hot ? "border-accent text-accent" : "border-line text-muted",
      )}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export function Button({
  tone = "accent",
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "accent" | "ghost" }) {
  return (
    <button
      className={cn(
        "inline-flex h-11 items-center justify-center rounded-md px-4 text-sm font-medium transition-transform duration-150 ease-out active:not-disabled:scale-[0.96] disabled:opacity-50",
        tone === "accent" ? "bg-accent text-ink" : "border border-line bg-transparent text-fg",
        className,
      )}
      {...props}
    >
      {children}
    </button>
  );
}

export function Panel({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("rounded-lg border border-line bg-elev", className)}>{children}</div>;
}

export function Empty({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-10">
      <p className="text-lg">{title}</p>
      <p className="mt-2 max-w-md text-sm text-muted">{body}</p>
    </div>
  );
}

export function LoadingLines() {
  return (
    <div className="space-y-3" aria-hidden>
      <div className="h-4 w-40 rounded-sm bg-surface" />
      <div className="h-24 rounded-lg border border-line bg-elev" />
      <div className="h-24 rounded-lg border border-line bg-elev" />
    </div>
  );
}
