import { useEffect, useMemo, useRef, useState } from "react";
import { Bot, MousePointerClick, Eye, ShieldCheck, ListChecks, LifeBuoy, AlertTriangle, Hand, Camera, Coins, Flag, ChevronLeft } from "lucide-react";
import { api, fmtTime, duration } from "../api";
import { Chip, Panel, KV, Code, Spinner, PageHeader } from "../components/ui";
import Operator from "../components/Operator";
import SessionWindow from "../components/SessionWindow";

const ICON: Record<string, any> = {
  "agent.decision": Bot, "agent.usage": Coins, "surface.observation": Eye, "surface.action": MousePointerClick, "policy.decision": ShieldCheck,
  "replay.step.started": ListChecks, "replay.step.finished": ListChecks, "replay.target.resolved": MousePointerClick, "replay.condition": ListChecks,
  "replay.recovery": LifeBuoy, "replay.outcome": Flag, "control.transition": Hand, "control.intervention": Hand, "control.human_action": Hand,
  "evidence.captured": Camera, error: AlertTriangle, "run.started": Flag, "run.finished": Flag,
};
const TONE: Record<string, string> = {
  "agent.decision": "text-accent-300", "surface.action": "text-sky-300", "policy.decision": "text-emerald-300", "replay.recovery": "text-amber-300",
  "replay.outcome": "text-sky-300", "control.transition": "text-violet-300", "control.intervention": "text-violet-300", "control.human_action": "text-violet-300",
  error: "text-rose-300", "run.finished": "text-ink-100",
};

function shotName(p?: string | null) { return p ? p.split("/").pop() : undefined; }

const sentence = (v: string) => v.charAt(0).toUpperCase() + v.slice(1);

export default function RunDetail({ runId }: { runId: string }) {
  const [run, setRun] = useState<any>(null);
  const [events, setEvents] = useState<any[]>([]);
  const [live, setLive] = useState(false);
  const [job, setJob] = useState<any>(null);
  const [shot, setShot] = useState<string | null>(null);
  const [follow, setFollow] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const listRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let es: EventSource | null = null;
    api.run(runId).then((r) => {
      setRun(r);
      if (r.status === "running") {
        setLive(true);
        setEvents([]);
        es = new EventSource(`/api/runs/${runId}/stream`);
        es.onmessage = (m) => setEvents((ev) => [...ev, JSON.parse(m.data)]);
        es.addEventListener("end", () => { es?.close(); setLive(false); api.run(runId).then(setRun); });
      } else setEvents(r.events_list);
    });
    return () => es?.close();
  }, [runId]);

  useEffect(() => {
    if (!run?.job_id) return;
    const load = () => api.job(run.job_id).then(setJob).catch(() => {});
    load();
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [run?.job_id]);

  const shots = useMemo(() => events.map((e) => shotName(e.data?.screenshot)).filter(Boolean) as string[], [events]);
  const shotEvent = useMemo(() => events.find((e) => shotName(e.data?.screenshot) === shot), [events, shot]);
  const lastUrl = useMemo(() => { const m = [...events].reverse().find((e) => /url=(\S+)/.test(e.message)); return m ? m.message.match(/url=(\S+)/)![1] : null; }, [events]);
  useEffect(() => { if (follow && shots.length) setShot(shots[shots.length - 1]); }, [shots, follow]);
  useEffect(() => { if (follow && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight; }, [events, follow]);

  if (!run) return <Spinner />;
  const result = run.result ?? job?.result;
  const usage = events.filter((e) => e.kind === "agent.usage").reduce((a, e) => ({ in: a.in + (e.data?.usage?.input_tokens ?? 0), out: a.out + (e.data?.usage?.output_tokens ?? 0), cached: a.cached + (e.data?.usage?.cache_read_input_tokens ?? 0) }), { in: 0, out: 0, cached: 0 });
  const decisions = events.filter((e) => e.kind === "agent.decision").length;
  const visible = showAll ? events : events.filter((e) => e.kind !== "agent.usage" && !(e.kind === "evidence.captured" && !e.data?.screenshot) && !(e.kind === "replay.condition" && !e.step_id && e.message.startsWith("ok")));
  const intervention = job?.intervention;

  return (
    <>
      <PageHeader
        title={<span className="flex items-center gap-3"><a href="#/runs" className="text-ink-400 hover:text-ink-100"><ChevronLeft className="w-5 h-5" /></a>{run.title.replace(/^(replay|discovery): ?/, "")}<Chip value={live ? "running" : run.status} />{live && <span className="pulse-dot w-2 h-2 rounded-full bg-amber-400" />}</span>}
        subtitle={<span className="font-mono">{runId}</span>}
        action={<div className="flex items-center gap-2"><Chip value={run.kind} /><Chip value={job?.owner ?? run.owner} /><label className="text-[12px] text-ink-400 flex items-center gap-1.5 ml-2"><input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} /> follow</label></div>} />

      {intervention && job && <div className="mb-4"><Operator jobId={job.id} /></div>}

      <div className="grid lg:grid-cols-[minmax(0,1fr)_460px] gap-4">
        <Panel title={<span>Timeline <span className="text-ink-400 font-normal tnum">{visible.length} events{decisions ? `, ${decisions} model decisions` : ""}</span></span>} action={<button className="text-[12px] text-ink-400 hover:text-ink-200" onClick={() => setShowAll(!showAll)}>{showAll ? "hide noise" : "show all"}</button>} padded={false}>
          <div ref={listRef} className="max-h-[calc(100vh-220px)] overflow-auto">
            {visible.map((e, k) => {
              const Icon = ICON[e.kind] ?? Flag;
              const tone = TONE[e.kind] ?? "text-ink-300";
              const sn = shotName(e.data?.screenshot);
              const isDecision = e.kind === "agent.decision";
              const fail = e.kind === "error" || (e.kind === "replay.condition" && e.message.startsWith("FAIL")) || e.data?.status === "failed" || e.message.startsWith("block");
              return (
                <div key={k} onClick={() => { if (sn) { setFollow(false); setShot(sn); } }} className={`flex gap-3 px-4 py-2 border-b border-ink-800/70 last:border-0 ${sn ? "cursor-pointer hover:bg-ink-850" : ""} ${sn === shot ? "bg-ink-850" : ""}`}>
                  <div className="w-[52px] shrink-0 font-mono text-[11px] text-ink-500 pt-0.5 tabular-nums">{fmtTime(e.ts)}</div>
                  <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${fail ? "text-rose-300" : tone}`} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className={`text-[12px] font-semibold ${fail ? "text-rose-300" : tone}`}>{sentence(e.kind.split(".").slice(-1)[0].replace(/_/g, " "))}</span>
                      {e.step_id && <span className="font-mono text-[11px] text-ink-400">{e.step_id}</span>}
                      {e.data?.strategy && <span className="chip bg-ink-800 text-ink-300 border border-ink-700 !normal-case">{e.data.strategy}#{e.data.index}</span>}
                      {e.data?.risk && <Chip value={e.data.risk} />}
                      {e.data?.status && e.kind === "replay.step.finished" && <Chip value={e.data.status === "ok" ? "success" : e.data.status} />}
                      {e.data?.recoveries?.length > 0 && <span className="chip bg-amber-500/15 text-amber-300 border border-amber-500/30 !normal-case">{e.data.recoveries.join(", ")}</span>}
                      {sn && <Camera className="w-3 h-3 text-ink-500" />}
                    </div>
                    <div className={`text-[13px] mt-0.5 break-words ${isDecision ? "text-ink-100 bg-accent/10 border border-accent/20 rounded-lg px-3 py-2 mt-1" : fail ? "text-rose-200" : "text-ink-200"}`}>{e.message}</div>
                    {e.data?.observed && <div className="text-[12px] text-ink-400 mt-0.5 truncate">observed: {e.data.observed}</div>}
                    {e.data?.expected && <div className="text-[12px] text-ink-400">expected: {e.data.expected}</div>}
                    {e.data?.target && e.kind === "control.human_action" && <div className="text-[12px] text-violet-300">{e.data.target.description}{e.data.value ? ` ← "${e.data.value}"` : ""}</div>}
                  </div>
                </div>
              );
            })}
            {events.length === 0 && <div className="p-6 text-[13px] text-ink-400">{live ? "Waiting for events…" : "No events."}</div>}
          </div>
        </Panel>

        <div className="space-y-4">
          <div>
            <div className="flex items-center justify-between mb-2">
              <div className="label">Screen{shot ? <span className="tnum text-ink-400"> {shots.indexOf(shot) + 1} of {shots.length}</span> : null}</div>
              {shots.length > 1 && !follow && <button className="btn !py-0.5 !px-2 text-[12px]" onClick={() => setFollow(true)}>Follow live</button>}
            </div>
            <SessionWindow src={shot ? `/api/runs/${runId}/files/screenshots/${shot}` : null} url={shotEvent?.data?.url ?? lastUrl} title={shotEvent?.data?.title ?? (run.kind === "discovery" ? "discovery" : "replay")} live={live} caption={shot} empty={live ? "Waiting for the first capture…" : "No screenshot in this run"}
              strip={shots.length > 1 ? (
                <div className="flex gap-1 overflow-x-auto pb-0.5">
                  {shots.map((s2: string) => (
                    <button
                      key={s2}
                      type="button"
                      title={s2}
                      onClick={() => { setFollow(false); setShot(s2); }}
                      className={`h-10 w-16 shrink-0 rounded-sm overflow-hidden border transition-colors ${
                        s2 === shot ? "border-attention" : "border-ink-700 hover:border-ink-500"
                      }`}
                    >
                      <img src={`/api/runs/${runId}/files/screenshots/${s2}`} alt="" className="w-full h-full object-cover object-top" />
                    </button>
                  ))}
                </div>
              ) : null} />
          </div>

          {result && (
            <Panel title="Result">
              <div className="flex items-center gap-2 mb-3"><Chip value={result.status} />{result.outcome_code && <span className="font-mono text-[12px] text-sky-300">{result.outcome_code}</span>}</div>
              {result.outputs && Object.keys(result.outputs).length > 0 && <div className="mb-3"><div className="label mb-1">Outputs</div><Code>{JSON.stringify(result.outputs, null, 2)}</Code></div>}
              {result.outcome_description && <p className="text-[13px] text-ink-300 mb-2">{result.outcome_description}</p>}
              {result.failure && <div className="mb-2"><div className="label mb-1 text-rose-300">Failure: {result.failure.failure_class}</div><KV rows={[["step", <span className="font-mono">{result.failure.step_id ?? "—"}</span>], ["message", result.failure.message], ["expected", result.failure.expected ?? "—"], ["observed", <span className="line-clamp-3">{result.failure.observed ?? "—"}</span>]]} /></div>}
              {result.handoff && <div className="mb-2"><div className="label mb-1 text-violet-300">Handoff</div><KV rows={[["resolution", result.handoff.resolution], ["operator", result.handoff.operator ?? "—"], ["human actions", String(result.handoff.human_actions)], ["reason", result.handoff.reason]]} /></div>}
              {result.summary && <p className="text-[13px] text-ink-300">{result.summary}</p>}
              {result.capability_id && <a className="btn mt-2" href={`#/capabilities/${result.capability_id}`}>Open recorded capability →</a>}
              {result.steps && <div className="mt-3 text-[12px] text-ink-400 tnum">{result.steps.length} steps in {duration(result.started_at, result.finished_at)}</div>}
            </Panel>
          )}

          <Panel title="Run">
            <KV rows={[["kind", <Chip value={run.kind} />], ["started", fmtTime(run.started_at)], ["duration", duration(run.started_at, run.finished_at) || "live"], ["events", String(run.events)], ...(usage.in ? [["tokens", <span className="tnum">{usage.in.toLocaleString()} in, {usage.out.toLocaleString()} out, {usage.cached.toLocaleString()} cached</span>] as [string, any]] : []), ["evidence", <span className="font-mono text-[12px]">runs/{runId}/</span>]]} />
            <div className="flex flex-wrap gap-1.5 mt-3">
              <a className="btn !py-1 !px-2 text-[12px]" href={`/api/runs/${runId}/files/events.jsonl`} target="_blank">events.jsonl</a>
              {run.files?.transcript && <a className="btn !py-1 !px-2 text-[12px]" href={`/api/runs/${runId}/files/transcript.json`} target="_blank">transcript.json</a>}
              {run.files?.capability && <a className="btn !py-1 !px-2 text-[12px]" href={`/api/runs/${runId}/files/capability.json`} target="_blank">capability.json</a>}
              {run.files?.snapshots?.slice(0, 3).map((s: string) => <a key={s} className="btn !py-1 !px-2 text-[12px]" href={`/api/runs/${runId}/files/snapshots/${s}`} target="_blank">DOM {s.split("-").slice(-1)[0].replace(".html", "")}</a>)}
            </div>
          </Panel>
        </div>
      </div>
    </>
  );
}
