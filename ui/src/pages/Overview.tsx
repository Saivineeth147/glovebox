import { useEffect, useState } from "react";
import { ArrowRight, Compass, Play } from "lucide-react";
import { api, duration, fmtDate } from "../api";
import { Chip, Empty, Panel, Spinner } from "../components/ui";
import { go } from "../App";

const REFRESH_MS = 3000;

const HOW_IT_WORKS = [
  ["Discover", "Claude operates the real interface once, through the same guardrails production uses."],
  ["Review", "What it recorded is a typed contract — inputs, outputs, outcomes, locators, risk."],
  ["Replay", "Agents invoke it by name. No model. Outcomes, recoveries and failures stay distinct."],
  ["Hand off", "When it is stuck or the step is risky, a person takes the live session and gives it back."],
];

/** One reading. The number leads; its name and note stay quiet beneath it. */
function Reading({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note?: string;
  tone?: "good" | "warn" | "bad";
}) {
  const colour =
    tone === "good" ? "text-emerald-300"
    : tone === "warn" ? "text-attention-300"
    : tone === "bad" ? "text-rose-300"
    : "text-ink-100";
  return (
    <div className="px-5 py-4">
      <div className="text-[12.5px] text-ink-400">{label}</div>
      <div className={`mt-2 text-[30px] leading-none font-semibold tracking-display tnum ${colour}`}>
        {value}
      </div>
      {note && <div className="mt-2 text-[12.5px] text-ink-500">{note}</div>}
    </div>
  );
}

export default function Overview() {
  const [ov, setOv] = useState<any>(null);

  useEffect(() => {
    const load = () => api.overview().then(setOv).catch(() => {});
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => clearInterval(timer);
  }, []);

  if (!ov) return <Spinner />;
  const rate = ov.replay_success_rate;
  const refresh = () => api.overview().then(setOv);

  return (
    <div className="enter">
      <header className="flex flex-wrap items-start justify-between gap-6 mb-9">
        <div className="max-w-[46ch]">
          <h1 className="text-[30px] leading-[1.15] font-semibold tracking-display text-ink-100">
            One run with the model.
            <br />
            Every run after it without one.
          </h1>
          <p className="mt-3 text-[14px] leading-relaxed text-ink-400">
            Glovebox records a single supervised pass over a legacy application and turns it into
            a reviewed, typed capability that agents call in production — deterministically, and
            with a person one click from the controls.
          </p>
        </div>
        <div className="flex gap-2.5 pt-1.5">
          <button className="btn" onClick={() => go("/capabilities")}>
            <Play className="w-3.5 h-3.5" /> Invoke a capability
          </button>
          <button className="btn btn-primary" onClick={() => go("/discover")}>
            <Compass className="w-3.5 h-3.5" /> New discovery
          </button>
        </div>
      </header>

      <div className="panel grid grid-cols-2 md:grid-cols-5 divide-x divide-y md:divide-y-0 divide-ink-700/70 overflow-hidden">
        <Reading label="Runs" value={String(ov.runs)} note={`${ov.replays} replays`} />
        <Reading
          label="Replay success"
          value={rate == null ? "—" : `${Math.round(rate * 100)}%`}
          note="of finished replays"
          tone={rate == null ? undefined : rate >= 0.9 ? "good" : rate >= 0.6 ? "warn" : "bad"}
        />
        <Reading
          label="Capabilities"
          value={String(ov.capabilities)}
          note={`${ov.approved} approved for unattended replay`}
        />
        <Reading
          label="Waiting on a person"
          value={String(ov.open_interventions)}
          note={ov.open_interventions ? "a run is paused for you" : "automation holds the lease"}
          tone={ov.open_interventions ? "warn" : undefined}
        />
        <Reading
          label="Target"
          value={ov.target.up ? "Up" : "Down"}
          note={ov.target.url}
          tone={ov.target.up ? "good" : "bad"}
        />
      </div>

      <div className="grid lg:grid-cols-[1fr_380px] gap-5 mt-5">
        <Panel
          title="Recent runs"
          action={
            <a href="#/runs" className="text-[12.5px] text-ink-400 hover:text-ink-100">
              All runs
            </a>
          }
          padded={false}
        >
          {ov.recent.length === 0 ? (
            <Empty>Nothing has run yet. Start a discovery, or invoke a capability.</Empty>
          ) : (
            <ul>
              {ov.recent.map((r: any) => (
                <li key={r.run_id}>
                  <button
                    type="button"
                    onClick={() => go(`/runs/${r.run_id}`)}
                    className="row w-full flex items-center gap-4 px-5 py-3.5 text-left border-b border-ink-800/70 last:border-0"
                  >
                    <Chip value={r.status} className="w-[104px] justify-center shrink-0" />
                    <span className="flex-1 min-w-0 truncate text-[13.5px] text-ink-200">
                      {r.title.replace(/^(replay|discovery): ?/, "")}
                    </span>
                    <span className="hidden sm:block text-[12.5px] text-ink-500 whitespace-nowrap">
                      {fmtDate(r.started_at)}
                    </span>
                    <span className="text-[12.5px] text-ink-500 tnum w-14 text-right">
                      {duration(r.started_at, r.finished_at)}
                    </span>
                    <ArrowRight className="w-4 h-4 text-ink-600 shrink-0" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="space-y-5">
          <Panel title="How it works">
            <ol className="space-y-4">
              {HOW_IT_WORKS.map(([name, what], index) => (
                <li key={name} className="flex gap-3.5">
                  <span className="mt-[3px] w-5 h-5 shrink-0 rounded-pill bg-ink-800 border border-ink-600 grid place-items-center text-[11px] text-ink-300 tnum">
                    {index + 1}
                  </span>
                  <span className="text-[13px] leading-relaxed text-ink-400">
                    <b className="text-ink-100 font-semibold">{name}.</b> {what}
                  </span>
                </li>
              ))}
            </ol>
          </Panel>

          <Panel
            title="Simulated faults"
            action={
              <button
                className="text-[12.5px] text-ink-400 hover:text-ink-100"
                onClick={() => api.clearFaults().then(refresh)}
              >
                Clear
              </button>
            }
          >
            <p className="hint mb-3">
              Arm a one-shot condition on the target to watch how replay answers it.
            </p>
            <div className="flex flex-wrap gap-2">
              {(ov.target.known ?? []).map((fault: string) => (
                <button
                  key={fault}
                  className={`btn !py-1 !px-3 text-[12px] ${
                    ov.target.armed?.[fault] ? "!border-attention-600 !text-attention-300" : ""
                  }`}
                  onClick={() => api.armFault(fault).then(refresh)}
                >
                  {fault.replace(/_/g, " ")}
                  {ov.target.armed?.[fault] ? " · armed" : ""}
                </button>
              ))}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
