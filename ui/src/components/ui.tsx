import { ReactNode } from "react";
import { Loader2 } from "lucide-react";

export const STATUS: Record<string, string> = {
  success: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  business_outcome: "bg-sky-500/15 text-sky-300 border border-sky-500/30",
  escalated: "bg-violet-500/15 text-violet-300 border border-violet-500/30",
  failed: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  error: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  running: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  queued: "bg-ink-700 text-ink-300 border border-ink-600",
  finished: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  max_steps: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  timeout: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  approved: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  draft: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  deprecated: "bg-ink-700 text-ink-300 border border-ink-600",
  read: "bg-ink-700 text-ink-200 border border-ink-600",
  reversible: "bg-sky-500/15 text-sky-300 border border-sky-500/30",
  irreversible: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  human: "bg-violet-500/15 text-violet-300 border border-violet-500/30",
  automation: "bg-emerald-500/15 text-emerald-300 border border-emerald-500/30",
  stuck: "bg-amber-500/15 text-amber-300 border border-amber-500/30",
  confirm: "bg-sky-500/15 text-sky-300 border border-sky-500/30",
  blocked: "bg-rose-500/15 text-rose-300 border border-rose-500/30",
  discovery: "bg-accent/15 text-accent-300 border border-accent/30",
  replay: "bg-ink-700 text-ink-200 border border-ink-600",
};

export function Chip({ value, className = "" }: { value?: string | null; className?: string }) {
  if (!value) return null;
  const v = String(value);
  return <span className={`chip ${STATUS[v] ?? "bg-ink-700 text-ink-200 border border-ink-600"} ${className}`}>{v.replace(/_/g, " ")}</span>;
}

export function Panel({ title, action, children, className = "", padded = true }: { title?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; padded?: boolean }) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between px-4 py-3 border-b border-ink-800">
          <h3 className="label">{title}</h3>
          {action}
        </header>
      )}
      <div className={padded ? "p-4" : ""}>{children}</div>
    </section>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "warn" | "bad" }) {
  const color = tone === "good" ? "text-emerald-300" : tone === "warn" ? "text-amber-300" : tone === "bad" ? "text-rose-300" : "text-ink-100";
  return (
    <div className="panel p-4">
      <div className="label">{label}</div>
      <div className={`mt-2 text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint && <div className="mt-1 text-xs text-ink-400">{hint}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-[13px] text-ink-400 py-8 text-center">{children}</div>;
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-ink-400 text-[13px]">
      <Loader2 className="w-4 h-4 animate-spin" /> {label ?? "Loading"}
    </div>
  );
}

export function KV({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-[13px]">
      {rows.map(([k, v]) => (
        <>
          <dt key={k + "k"} className="text-ink-400 whitespace-nowrap">{k}</dt>
          <dd key={k + "v"} className="text-ink-100 break-words min-w-0">{v}</dd>
        </>
      ))}
    </dl>
  );
}

export function Code({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <pre className={`font-mono text-[12px] leading-relaxed bg-ink-950 border border-ink-800 rounded-lg p-3 overflow-auto ${className}`}>{children}</pre>;
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12px] text-ink-300">{children}</span>;
}

export function PageHeader({ title, subtitle, action }: { title: ReactNode; subtitle?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex items-end justify-between mb-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        {subtitle && <p className="text-[13px] text-ink-400 mt-1">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
