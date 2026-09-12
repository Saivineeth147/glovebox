import { useEffect, useState } from "react";
import { ChevronLeft, Play, CheckCircle2 } from "lucide-react";
import { api, fmtDate } from "../api";
import { Chip, Panel, KV, Spinner, PageHeader, Code } from "../components/ui";
import { go } from "../App";

export default function CapabilityDetail({ id }: { id: string }) {
  const [c, setC] = useState<any>(null);
  const [params, setParams] = useState<Record<string, string>>({});
  const [faults, setFaults] = useState<string[]>([]);
  const [tenant, setTenant] = useState<string>("");
  const [attended, setAttended] = useState(true);
  const [allowDraft, setAllowDraft] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [known, setKnown] = useState<string[]>([]);
  useEffect(() => { api.capability(id).then((cap) => { setC(cap); setTenant(cap.app.tenant ?? ""); setParams(Object.fromEntries(cap.inputs.filter((p: any) => !p.sensitive).map((p: any) => [p.name, p.example ?? p.default ?? ""]))); }); api.overview().then((o) => setKnown(o.target.known ?? [])); }, [id]);
  if (!c) return <Spinner />;

  const invoke = async () => {
    setBusy(true); setErr(null);
    try {
      const job = await api.replay({ capability_id: c.id, params, tenant: tenant || null, attended, allow_draft: allowDraft || c.review.status !== "approved", faults });
      const wait = async () => { const j = await api.job(job.id); if (j.run_id) go(`/runs/${j.run_id}`); else setTimeout(wait, 300); };
      wait();
    } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const approve = async () => {
    const reviewer = window.prompt("Reviewer name", localStorage.getItem("gb-operator") || "") || "";
    if (!reviewer) return;
    const notes = window.prompt("Review notes (optional)") || undefined;
    setC(await api.approve(c.id, reviewer, notes));
  };

  return (
    <>
      <PageHeader title={<span className="flex items-center gap-3"><a href="#/capabilities" className="text-ink-400 hover:text-ink-100"><ChevronLeft className="w-5 h-5" /></a>{c.title}<Chip value={c.review.status} /><Chip value={c.max_risk} /></span>}
        subtitle={<span className="font-mono">{c.id}@{c.version} · schema {c.schema_version} · {c.app.app_id} / {c.app.tenant}</span>}
        action={c.review.status !== "approved" ? <button className="btn btn-success" onClick={approve}><CheckCircle2 className="w-3.5 h-3.5" /> Approve for unattended replay</button> : <span className="text-[12px] text-ink-400">approved by {c.review.reviewed_by} · {fmtDate(c.review.reviewed_at)}</span>} />

      <div className="grid lg:grid-cols-[minmax(0,1fr)_380px] gap-4">
        <div className="space-y-4">
          <Panel title="Contract"><p className="text-[13px] text-ink-200 mb-3">{c.description}</p>
            <div className="grid md:grid-cols-2 gap-4">
              <div><div className="label mb-1.5">Inputs</div>{c.inputs.map((p: any) => <div key={p.name} className="text-[13px] py-1 border-b border-ink-800 last:border-0"><span className="font-mono text-accent-300">{p.name}</span> <span className="text-ink-400">{p.type}{p.required ? "" : "?"}{p.sensitive ? " · sensitive" : ""}{p.pattern ? ` · /${p.pattern}/` : ""}</span><div className="text-ink-300">{p.description}</div></div>)}</div>
              <div><div className="label mb-1.5">Outputs</div>{c.outputs.map((o: any) => <div key={o.name} className="text-[13px] py-1 border-b border-ink-800 last:border-0"><span className="font-mono text-emerald-300">{o.name}</span> <span className="text-ink-400">{o.type}</span><div className="text-ink-300">{o.description}</div></div>)}
                <div className="label mt-3 mb-1.5">Success when</div>{c.success.map((s: any, k: number) => <div key={k} className="text-[13px] text-ink-300">{s.kind}: <span className="font-mono">{s.value}</span></div>)}</div>
            </div>
          </Panel>
          <Panel title={`Steps · ${c.steps.length}`} padded={false}>
            {c.steps.map((s: any, k: number) => (
              <div key={s.id} className="border-b border-ink-800 last:border-0">
                <div onClick={() => setOpen(open === s.id ? null : s.id)} className="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-ink-850 text-[13px]">
                  <span className="font-mono text-[11px] text-ink-500 w-6">{k + 1}</span>
                  <span className="chip bg-ink-800 text-ink-200 border border-ink-700 w-[86px] justify-center">{s.action}</span>
                  <span className="flex-1 text-ink-100 truncate">{s.intent}</span>
                  {s.target && <span className="text-ink-400 truncate max-w-[220px]">{s.target.description}</span>}
                  {s.value && <span className="font-mono text-[12px] text-ink-400 truncate max-w-[180px]">{s.value}</span>}
                  <Chip value={s.risk} />
                </div>
                {open === s.id && (
                  <div className="px-4 pb-3 pl-14 text-[12px] space-y-2 fade-in">
                    {s.target && <div><div className="label mb-1">Locator strategies · frame {s.target.frame.join("/") || "top"}</div>
                      {s.target.strategies.map((st: any, i: number) => <div key={i} className="flex gap-2 py-1 border-b border-ink-800/60 last:border-0"><span className="font-mono text-ink-500 w-4">{i}</span><span className="font-mono text-accent-300 w-20">{st.kind}</span><span className="font-mono text-ink-300 flex-1 truncate">{JSON.stringify(st.value)}</span><span className="text-ink-400 flex-1">{st.robustness}</span></div>)}</div>}
                    {s.expect?.length > 0 && <div><div className="label mb-1">Expect</div>{s.expect.map((e: any, i: number) => <div key={i} className="font-mono text-ink-300">{e.kind}: {e.value}</div>)}</div>}
                    {s.extract_to && <div className="text-ink-300">extracts → <span className="font-mono text-emerald-300">{s.extract_to}</span></div>}
                    {s.dialog_response && <div className="text-ink-300">next native dialog → {s.dialog_response}</div>}
                  </div>
                )}
              </div>
            ))}
          </Panel>
          <div className="grid md:grid-cols-3 gap-4">
            <Panel title="Business outcomes">{c.outcomes.length ? c.outcomes.map((o: any) => <div key={o.code} className="text-[12px] py-1.5 border-b border-ink-800 last:border-0"><span className="font-mono text-sky-300">{o.code}</span><div className="text-ink-300">{o.description}</div><div className="text-ink-500">detect: "{o.detect.value}"</div>{!o.verified && <div className="mt-1.5 text-[12px] text-attention-300">Detector never seen during discovery. Replay will report a hard failure instead of this outcome; do not branch on it until it is re-recorded against that screen.</div>}</div>) : <span className="text-[12px] text-ink-500">none declared</span>}</Panel>
            <Panel title="Recoveries">{c.recoveries.map((r: any) => <div key={r.name} className="text-[12px] py-1.5 border-b border-ink-800 last:border-0"><span className="font-mono text-amber-300">{r.name}</span> <span className="text-ink-400">→ {r.then} (max {r.max_attempts})</span><div className="text-ink-500">detect: "{r.detect.value}"</div></div>)}</Panel>
            <Panel title="Failure signals">{c.failure_signals.map((f: any, i: number) => <div key={i} className="text-[12px] py-1.5 border-b border-ink-800 last:border-0 font-mono text-rose-300">{f.kind}: {f.value}</div>)}
              <div className="label mt-3 mb-1">Provenance</div><KV rows={[["run", <a className="font-mono text-[11px] text-accent-300" href={`#/runs/${c.provenance.discovery_run_id}`}>{c.provenance.discovery_run_id}</a>], ["model", c.provenance.model], ["transcript", <span className="font-mono text-[11px]">{c.provenance.transcript_sha256.slice(0, 12)}…</span>]]} /></Panel>
          </div>
          {c.overrides.length > 0 && <Panel title="Tenant overrides"><Code className="max-h-60">{JSON.stringify(c.overrides, null, 2)}</Code></Panel>}
        </div>

        <div className="space-y-4">
          <Panel title="Invoke (deterministic replay)">
            <div className="space-y-3">
              {c.inputs.filter((p: any) => !p.sensitive).map((p: any) => <div key={p.name}><div className="label mb-1">{p.name}{p.required ? "" : " (optional)"}</div><input className="input font-mono" value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} placeholder={p.example ?? p.pattern ?? ""} /><div className="text-[11px] text-ink-500 mt-1">{p.description}</div></div>)}
              {c.inputs.some((p: any) => p.sensitive) && <div className="text-[12px] text-ink-400">Sensitive inputs ({c.inputs.filter((p: any) => p.sensitive).map((p: any) => p.name).join(", ")}) are supplied from the environment and never shown.</div>}
              <div><div className="label mb-1">Tenant</div><select className="input" value={tenant} onChange={(e) => setTenant(e.target.value)}><option value={c.app.tenant ?? ""}>{c.app.tenant} (recorded)</option>{c.overrides.map((o: any) => <option key={o.tenant} value={o.tenant}>{o.tenant} (override)</option>)}</select></div>
              <div><div className="label mb-1">Inject a runtime fault</div><div className="flex flex-wrap gap-1.5">{known.map((f) => <button key={f} className={`btn !py-1 !px-2 text-[12px] ${faults.includes(f) ? "border-amber-500/60 text-amber-300" : ""}`} onClick={() => setFaults(faults.includes(f) ? faults.filter((x) => x !== f) : [...faults, f])}>{f}</button>)}</div></div>
              <label className="flex items-center gap-2 text-[13px]"><input type="checkbox" checked={attended} onChange={(e) => setAttended(e.target.checked)} /> Attended — I will take over if it gets stuck</label>
              {c.review.status !== "approved" && <label className="flex items-center gap-2 text-[13px] text-amber-300"><input type="checkbox" checked={allowDraft} onChange={(e) => setAllowDraft(e.target.checked)} /> Allow draft (dev only; production refuses drafts)</label>}
              {err && <div className="text-[12px] text-rose-300">{err}</div>}
              <button className="btn btn-primary w-full justify-center" disabled={busy || (c.review.status !== "approved" && !allowDraft)} onClick={invoke}><Play className="w-3.5 h-3.5" /> {busy ? "Starting…" : "Replay now"}</button>
            </div>
          </Panel>
          <Panel title="Review">
            <KV rows={[["status", <Chip value={c.review.status} />], ["replays", `${c.review.replay_successes}/${c.review.replays} successful`], ["reviewed by", c.review.reviewed_by ?? "—"], ["notes", c.review.notes ?? "—"], ["created", fmtDate(c.created_at)]]} />
          </Panel>
        </div>
      </div>
    </>
  );
}
