import { useEffect, useState } from "react";
import { ArrowRight, Play, Compass } from "lucide-react";
import { api, fmtDate, duration } from "../api";
import { Chip, Panel, Stat, Empty, Spinner, PageHeader } from "../components/ui";
import { go } from "../App";

export default function Overview() {
  const [ov, setOv] = useState<any>(null);
  useEffect(() => {
    const load = () => api.overview().then(setOv);
    load();
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, []);
  if (!ov) return <Spinner />;
  const rate = ov.replay_success_rate;
  return (
    <>
      <PageHeader title="Overview" subtitle="Discover once with the model, replay deterministically, hand off to a human when it matters."
        action={<div className="flex gap-2"><button className="btn" onClick={() => go("/capabilities")}><Play className="w-3.5 h-3.5" /> Invoke a capability</button><button className="btn btn-primary" onClick={() => go("/discover")}><Compass className="w-3.5 h-3.5" /> New discovery</button></div>} />
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <Stat label="Runs" value={ov.runs} hint={`${ov.replays} replays`} />
        <Stat label="Replay success" value={rate == null ? "—" : `${Math.round(rate * 100)}%`} tone={rate == null ? undefined : rate >= 0.9 ? "good" : rate >= 0.6 ? "warn" : "bad"} hint="success ÷ finished replays" />
        <Stat label="Capabilities" value={ov.capabilities} hint={`${ov.approved} approved`} />
        <Stat label="Open interventions" value={ov.open_interventions} tone={ov.open_interventions ? "warn" : undefined} hint={ov.open_interventions ? "a human is needed" : "automation in control"} />
        <Stat label="Target" value={ov.target.up ? "Up" : "Down"} tone={ov.target.up ? "good" : "bad"} hint={<span className="font-mono">{ov.target.url}</span>} />
      </div>
      <div className="grid md:grid-cols-[1fr_360px] gap-4 mt-4">
        <Panel title="Recent runs" action={<a href="#/runs" className="text-[12px] text-accent-300 hover:underline">All runs</a>} padded={false}>
          {ov.recent.length === 0 ? <Empty>No runs yet. Start a discovery or invoke a capability.</Empty> : (
            <table className="w-full text-[13px]">
              <tbody>
                {ov.recent.map((r: any) => (
                  <tr key={r.run_id} onClick={() => go(`/runs/${r.run_id}`)} className="border-b border-ink-800 last:border-0 hover:bg-ink-850 cursor-pointer">
                    <td className="px-4 py-2.5 w-[110px]"><Chip value={r.status} /></td>
                    <td className="px-2 py-2.5 w-[90px]"><Chip value={r.kind} /></td>
                    <td className="px-2 py-2.5 truncate max-w-[380px] text-ink-200">{r.title.replace(/^(replay|discovery): ?/, "")}</td>
                    <td className="px-2 py-2.5 text-ink-400 whitespace-nowrap">{fmtDate(r.started_at)}</td>
                    <td className="px-2 py-2.5 text-ink-400 tabular-nums">{duration(r.started_at, r.finished_at)}</td>
                    <td className="px-3 py-2.5 text-ink-500"><ArrowRight className="w-3.5 h-3.5" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Panel>
        <div className="space-y-4">
          <Panel title="How it works">
            <ol className="text-[13px] text-ink-300 space-y-2.5 list-decimal pl-4">
              <li><b className="text-ink-100">Discover.</b> Claude operates the real UI once, through the same guardrails production uses.</li>
              <li><b className="text-ink-100">Review.</b> The recorded capability is a typed contract: inputs, outputs, outcomes, locators, risk.</li>
              <li><b className="text-ink-100">Replay.</b> Agents invoke it by name. No model. Business outcomes, recoveries and failures are distinct.</li>
              <li><b className="text-ink-100">Hand off.</b> When stuck or risky, a human takes the same live session and hands it back.</li>
            </ol>
          </Panel>
          <Panel title="Simulated faults" action={<button className="text-[12px] text-ink-400 hover:text-ink-200" onClick={() => api.clearFaults().then(() => api.overview().then(setOv))}>clear</button>}>
            <p className="text-[12px] text-ink-400 mb-2">Arm a one-shot runtime condition on the target app to see how replay handles it.</p>
            <div className="flex flex-wrap gap-1.5">
              {(ov.target.known ?? []).map((f: string) => (
                <button key={f} className={`btn !py-1 !px-2 text-[12px] ${ov.target.armed?.[f] ? "border-amber-500/60 text-amber-300" : ""}`} onClick={() => api.armFault(f).then(() => api.overview().then(setOv))}>
                  {f}{ov.target.armed?.[f] ? " · armed" : ""}
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
