import { Fragment, ReactNode } from "react";
import { Loader2 } from "lucide-react";

/**
 * Status colour carries meaning, so it is the only colour in the interface that is allowed to
 * vary. Automation green, human amber, stop red, and a neutral steel for facts that are not a
 * state at all (the kind of a run, the risk class of a step).
 */
export const STATUS: Record<string, string> = {
  success: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  finished: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  approved: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  automation: "bg-emerald-500/10 text-emerald-300 border-emerald-500/25",
  business_outcome: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  reversible: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  confirm: "bg-sky-500/10 text-sky-300 border-sky-500/25",
  human: "bg-attention/10 text-attention-300 border-attention/30",
  escalated: "bg-attention/10 text-attention-300 border-attention/30",
  stuck: "bg-attention/10 text-attention-300 border-attention/30",
  running: "bg-attention/10 text-attention-300 border-attention/30",
  draft: "bg-attention/10 text-attention-300 border-attention/30",
  failed: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  error: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  blocked: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  max_steps: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  timeout: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  irreversible: "bg-rose-500/10 text-rose-300 border-rose-500/25",
  queued: "bg-ink-800 text-ink-300 border-ink-600",
  deprecated: "bg-ink-800 text-ink-300 border-ink-600",
  read: "bg-ink-800 text-ink-200 border-ink-600",
  replay: "bg-ink-800 text-ink-200 border-ink-600",
  discovery: "bg-ink-800 text-ink-200 border-ink-600",
};

const NEUTRAL = "bg-ink-800 text-ink-200 border-ink-600";

function sentence(value: string): string {
  const words = value.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function Chip({ value, className = "" }: { value?: string | null; className?: string }) {
  if (!value) return null;
  return (
    <span className={`chip ${STATUS[String(value)] ?? NEUTRAL} ${className}`}>
      {sentence(String(value))}
    </span>
  );
}

export function Panel({
  title,
  action,
  children,
  className = "",
  padded = true,
}: {
  title?: ReactNode;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  padded?: boolean;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <header className="flex items-center justify-between gap-3 px-5 h-[52px] border-b border-ink-800/80">
          <h2 className="text-[13.5px] font-semibold text-ink-100">{title}</h2>
          {action}
        </header>
      )}
      <div className={padded ? "p-5" : ""}>{children}</div>
    </section>
  );
}

/** A reading, not a marketing figure: the number leads, the unit and note stay quiet. */
export function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
  tone?: "good" | "warn" | "bad";
}) {
  const color =
    tone === "good" ? "text-emerald-300"
    : tone === "warn" ? "text-attention-300"
    : tone === "bad" ? "text-rose-300"
    : "text-ink-100";
  return (
    <div className="px-4 py-3">
      <div className="label">{label}</div>
      <div className={`mt-1.5 text-[26px] leading-none font-semibold tnum ${color}`}>{value}</div>
      {hint && <div className="mt-1.5 hint">{hint}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="text-[13px] text-ink-400 py-10 text-center">{children}</div>;
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
    <dl className="grid grid-cols-[auto_1fr] gap-x-5 gap-y-2 text-[13px]">
      {rows.map(([key, value]) => (
        <Fragment key={key}>
          <dt className="text-ink-400 whitespace-nowrap">{key}</dt>
          <dd className="text-ink-100 break-words min-w-0">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

export function Code({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <pre className={`recess font-mono text-[12px] leading-relaxed p-3 overflow-auto ${className}`}>
      {children}
    </pre>
  );
}

export function Mono({ children }: { children: ReactNode }) {
  return <span className="font-mono text-[12px] text-ink-300 tnum">{children}</span>;
}

export function PageHeader({
  title,
  subtitle,
  action,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-6 mb-7">
      <div className="min-w-0">
        <h1 className="text-[24px] leading-tight font-semibold tracking-display text-ink-100">{title}</h1>
        {subtitle && <p className="hint mt-2 max-w-[68ch]">{subtitle}</p>}
      </div>
      {action}
    </div>
  );
}
