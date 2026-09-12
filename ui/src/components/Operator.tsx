import { useEffect, useRef, useState } from "react";
import { Hand, RefreshCw } from "lucide-react";
import { api, fmtTime } from "../api";
import { Chip } from "./ui";
import BrowserFrame from "./BrowserFrame";

/** Human takeover of the live session for one job. A client of the OperatorBridge — nothing here touches the browser. */
export default function Operator({ jobId, onResolved }: { jobId: string; onResolved?: () => void }) {
  const [st, setSt] = useState<any>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [text, setText] = useState("");
  const [nav, setNav] = useState("");
  const [who, setWho] = useState(localStorage.getItem("gb-operator") || "");
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const shotRef = useRef<string | null>(null);
  const [shotUrl, setShotUrl] = useState<string | null>(null);

  const refresh = () => api.operator(jobId).then((s) => { setSt(s); if (s.screenshot && s.screenshot !== shotRef.current) { shotRef.current = s.screenshot; setShotUrl(s.screenshot); } }).catch(() => {});
  useEffect(() => { refresh(); const t = setInterval(refresh, 1500); return () => clearInterval(t); }, [jobId]);
  useEffect(() => { localStorage.setItem("gb-operator", who); }, [who]);

  const say = (m: string) => { setToast(m); setTimeout(() => setToast(null), 2200); };
  const act = async (op: string) => {
    const body: any = { op, operator: who || "studio-user" };
    if (["click", "fill", "select", "press"].includes(op)) {
      if (!sel && op !== "press") return say("Pick an element first");
      if (sel) body.ref = sel;
      if (op === "fill") body.text = text; if (op === "select") body.option = text; if (op === "press") body.key = text || "Enter";
    }
    if (op === "navigate") { if (!nav) return say("Enter a URL"); body.url = nav; }
    if (op === "abort" || op === "decline") body.note = window.prompt("Note for the run log (optional)") || undefined;
    setBusy(true);
    try {
      const r = await api.command(jobId, body);
      say(r.ok ? (r.resolution ? `Control handed back: ${r.resolution}` : `${op} done`) : r.error || "failed");
      if (r.resolution) onResolved?.();
    } catch (e: any) { say(e.message); }
    setBusy(false); setSel(null); refresh();
  };

  const i = st?.intervention;
  const human = st?.owner === "human";
  const [vw, vh] = st?.viewport ?? [1100, 800];
  const selected = st?.elements?.find((e: any) => e.ref === sel);

  return (
    <div className="panel border-violet-500/40 overflow-hidden fade-in">
      <header className="px-4 py-3 border-b border-ink-800 bg-violet-500/10 flex items-center gap-3">
        <div className="w-7 h-7 rounded-lg bg-violet-500/30 grid place-items-center"><Hand className="w-4 h-4 text-violet-200" /></div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-semibold text-violet-100 flex items-center gap-2">Human handoff {i && <Chip value={i.kind} />} <Chip value={st?.owner} /></div>
          <div className="text-[12px] text-ink-300 truncate">{i ? i.reason : "Waiting for an intervention…"}</div>
        </div>
        <label className="text-[11px] text-ink-400 flex items-center gap-2">You are <input className="input !w-36 !py-1" value={who} onChange={(e) => setWho(e.target.value)} placeholder="operator" /></label>
      </header>
      {i && (
        <div className="px-4 py-2.5 border-b border-ink-800 grid grid-cols-2 md:grid-cols-4 gap-x-4 gap-y-1 text-[12px]">
          <div><span className="text-ink-400">Capability</span> <span className="font-mono">{i.capability_id ?? "—"}</span></div>
          <div><span className="text-ink-400">Step</span> <span className="font-mono">{i.step_id ?? "—"}</span></div>
          <div><span className="text-ink-400">Opened</span> {fmtTime(i.created_at)}</div>
          <div className="truncate"><span className="text-ink-400">Goal</span> {i.goal ?? "—"}</div>
          {i.observed && <details className="col-span-full"><summary className="cursor-pointer text-ink-400 hover:text-ink-200">What the automation saw</summary><pre className="font-mono text-[11px] whitespace-pre-wrap mt-1 p-2 bg-ink-950 rounded-lg border border-ink-800 max-h-40 overflow-auto">{i.observed}</pre></details>}
        </div>
      )}
      <div className="grid lg:grid-cols-[1fr_320px]">
        <div className="p-4 border-r border-ink-800">
          <div className="label mb-2">Live session · {st?.elements?.length ?? 0} interactive elements · click a highlighted control to select it</div>
          <BrowserFrame src={shotUrl} url={st?.url} live={human} aspect={`${vw}/${vh}`} empty="Waiting for the session's first capture…"
            overlay={st?.elements?.map((e: any) => {
              const [x, y, w, h] = e.box; if (w <= 0 || h <= 0) return null;
              return <div key={e.ref} title={`${e.ref} ${e.role} ${e.name || ""}`} onClick={() => setSel(e.ref)}
                className={`absolute rounded-[3px] cursor-pointer transition-colors border ${sel === e.ref ? "border-violet-400 bg-violet-400/30 ring-2 ring-violet-400/40" : "border-accent/70 bg-accent/10 hover:bg-accent/30"}`}
                style={{ left: `${(100 * x) / vw}%`, top: `${(100 * y) / vh}%`, width: `${(100 * w) / vw}%`, height: `${(100 * h) / vh}%` }} />;
            })} />
          <div className="mt-3 max-h-44 overflow-auto rounded-lg border border-ink-800 divide-y divide-ink-800">
            {(st?.elements ?? []).map((e: any) => (
              <div key={e.ref} onClick={() => setSel(e.ref)} className={`flex items-center gap-3 px-3 py-1.5 text-[12px] cursor-pointer ${sel === e.ref ? "bg-violet-500/15" : "hover:bg-ink-850"}`}>
                <span className="font-mono text-ink-500 w-8">{e.ref}</span><span className="text-ink-400 w-16">{e.role}</span>
                <span className="text-ink-100 truncate">{e.name || e.label || e.text}</span>
                {e.name_attr && <span className="font-mono text-ink-500">name={e.name_attr}</span>}
                <span className="ml-auto text-ink-500">{e.frame || "top"}</span>
              </div>
            ))}
          </div>
        </div>
        <div className="p-4 space-y-4">
          <div>
            <div className="label mb-2">Act on the live session</div>
            <div className="rounded-lg bg-ink-850 border border-ink-800 px-3 py-2 text-[12px] min-h-[38px]">
              {selected ? <><b>{selected.role}</b> {selected.name || selected.label || selected.text} <span className="text-ink-400">· {selected.ref}</span>{selected.options?.length ? <div className="text-ink-400 mt-0.5">options: {selected.options.join(", ")}</div> : null}</> : <span className="text-ink-400">Pick an element on the screenshot or in the list.</span>}
            </div>
            <input className="input mt-2" placeholder="text to type · option · key (Enter)" value={text} onChange={(e) => setText(e.target.value)} />
            <div className="flex flex-wrap gap-1.5 mt-2">
              <button className="btn btn-primary" disabled={!human || busy} onClick={() => act("click")}>Click</button>
              <button className="btn" disabled={!human || busy} onClick={() => act("fill")}>Fill</button>
              <button className="btn" disabled={!human || busy} onClick={() => act("select")}>Select</button>
              <button className="btn" disabled={!human || busy} onClick={() => act("press")}>Press</button>
              <button className="btn" disabled={!human || busy} onClick={() => act("observe")} title="re-observe"><RefreshCw className="w-3.5 h-3.5" /></button>
            </div>
            <div className="flex gap-1.5 mt-2"><input className="input" placeholder="URL within the allowlist" value={nav} onChange={(e) => setNav(e.target.value)} /><button className="btn" disabled={!human || busy} onClick={() => act("navigate")}>Go</button></div>
          </div>
          <div>
            <div className="label mb-2">Hand control back</div>
            <div className="space-y-2">
              {[
                ["resume", "Resume", "btn-success", "Retry the current step. You cleared the obstacle."],
                ["restart", "Restart", "", "Re-run from the entry step. Your fix reset the form or session."],
                ["complete", "Complete", "btn-human", "You finished by hand. Glovebox verifies success and extracts outputs."],
                ["abort", "Abort", "btn-danger", "Stop the run; the caller gets escalated."],
              ].map(([op, label, cls, hint]) => (
                <div key={op} className="flex items-start gap-3"><button className={`btn ${cls} w-24 justify-center`} disabled={!human || busy} onClick={() => act(op)}>{label}</button><p className="text-[12px] text-ink-400 leading-snug pt-1">{hint}</p></div>
              ))}
              {i?.kind === "confirm" && (
                <div className="flex items-start gap-3 pt-1 border-t border-ink-800"><button className="btn btn-success w-24 justify-center" disabled={busy} onClick={() => act("approve")}>Approve</button><button className="btn btn-danger w-24 justify-center" disabled={busy} onClick={() => act("decline")}>Decline</button><p className="text-[12px] text-ink-400 leading-snug pt-1">Irreversible step awaiting your decision.</p></div>
              )}
            </div>
          </div>
          <div>
            <div className="label mb-2">Your actions</div>
            {(st?.actions ?? []).length === 0 ? <div className="text-[12px] text-ink-500">Nothing yet.</div> : (
              <ul className="space-y-1 text-[12px]">{[...(st.actions as any[])].reverse().map((a, k) => <li key={k} className="flex gap-2"><span className="text-ink-500 tabular-nums">{fmtTime(a.ts)}</span><span className="text-violet-300 font-medium">{a.operator}</span><span className="truncate">{a.op} {a.target?.description ?? a.url ?? a.key ?? ""}{a.value ? ` ← "${a.value}"` : ""}</span></li>)}</ul>
            )}
          </div>
        </div>
      </div>
      {toast && <div className="fixed bottom-5 left-1/2 -translate-x-1/2 bg-ink-100 text-ink-950 text-[13px] px-4 py-2 rounded-lg shadow-lg fade-in">{toast}</div>}
    </div>
  );
}
