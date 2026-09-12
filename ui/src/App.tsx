import React, { useEffect, useState } from "react";
import { Activity, BookOpen, Compass, LayoutDashboard, ShieldCheck } from "lucide-react";
import Overview from "./pages/Overview";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";
import Capabilities from "./pages/Capabilities";
import CapabilityDetail from "./pages/CapabilityDetail";
import Discover from "./pages/Discover";
import Policy from "./pages/Policy";
import { api } from "./api";

export function useRoute() {
  const [hash, setHash] = useState(window.location.hash || "#/");
  useEffect(() => {
    const on = () => setHash(window.location.hash || "#/");
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return hash.replace(/^#/, "");
}

export function go(path: string) {
  window.location.hash = path;
}

const NAV = [
  { path: "/", label: "Overview", icon: LayoutDashboard },
  { path: "/runs", label: "Runs", icon: Activity },
  { path: "/capabilities", label: "Capabilities", icon: BookOpen },
  { path: "/discover", label: "Discover", icon: Compass },
  { path: "/policy", label: "Policy", icon: ShieldCheck },
];

const OVERVIEW_POLL_MS = 5000;

/** One reading in the containment band: a lamp, a word, and the value it is reporting. */
function Reading({ tone, label, value }: { tone: string; label: string; value: string }) {
  return (
    <span className="flex items-center gap-1.5 whitespace-nowrap">
      <span className={`lamp ${tone}`} />
      <span className="text-ink-400">{label}</span>
      <span className="text-ink-200 font-mono tnum">{value}</span>
    </span>
  );
}

export default function App() {
  const route = useRoute();
  const [ov, setOv] = useState<any>(null);

  useEffect(() => {
    const load = () => api.overview().then(setOv).catch(() => setOv({ target: { up: false } }));
    load();
    const timer = setInterval(load, OVERVIEW_POLL_MS);
    return () => clearInterval(timer);
  }, []);

  let page: React.ReactElement;
  const match = (re: RegExp) => route.match(re);
  if (match(/^\/runs\/([^/]+)$/)) page = <RunDetail runId={match(/^\/runs\/([^/]+)$/)![1]} />;
  else if (route === "/runs") page = <Runs />;
  else if (match(/^\/capabilities\/([^/]+)$/))
    page = <CapabilityDetail id={match(/^\/capabilities\/([^/]+)$/)![1]} />;
  else if (route === "/capabilities") page = <Capabilities />;
  else if (route === "/discover") page = <Discover />;
  else if (route === "/policy") page = <Policy />;
  else page = <Overview />;

  const isActive = (path: string) => (path === "/" ? route === "/" : route.startsWith(path));
  const interventions = ov?.open_interventions ?? 0;

  return (
    <div className="h-full flex flex-col">
      {/* Containment band: what is true of the whole enclosure, always visible. */}
      <header className="h-band shrink-0 flex items-center gap-4 px-3 border-b border-ink-700 bg-ink-900">
        <a href="#/" className="flex items-baseline gap-2 shrink-0">
          <span className="text-[13px] font-semibold tracking-[0.14em] text-ink-100">GLOVEBOX</span>
          <span className="hint hidden sm:inline">Studio</span>
        </a>
        <div className="flex-1" />
        <div className="flex items-center gap-4 text-[12px] overflow-x-auto">
          <Reading
            tone={interventions > 0 ? "text-attention-300 live" : "text-emerald-400"}
            label="control"
            value={interventions > 0 ? `human · ${interventions} waiting` : "automation"}
          />
          <Reading
            tone={ov?.target?.up ? "text-emerald-400" : "text-rose-400"}
            label="target"
            value={ov?.target?.up ? "reachable" : "offline"}
          />
          <Reading
            tone={ov?.has_api_key ? "text-emerald-400" : "text-ink-500"}
            label="model"
            value={ov?.has_api_key ? ov.model : "offline mode"}
          />
          <Reading tone="text-ink-500" label="policy" value={ov?.policy ?? "—"} />
        </div>
      </header>

      <div className="flex-1 min-h-0 flex">
        <nav
          aria-label="Sections"
          className="w-rail shrink-0 border-r border-ink-700 bg-ink-900 flex flex-col items-center py-2 gap-1"
        >
          {NAV.map(({ path, label, icon: Icon }) => (
            <a
              key={path}
              href={`#${path}`}
              title={label}
              aria-current={isActive(path) ? "page" : undefined}
              className={`relative w-10 h-10 grid place-items-center rounded-panel transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-attention/60 ${
                  isActive(path)
                    ? "bg-ink-700 text-ink-100"
                    : "text-ink-400 hover:bg-ink-800 hover:text-ink-200"
                }`}
            >
              <Icon className="w-[18px] h-[18px]" />
              <span className="sr-only">{label}</span>
              {path === "/runs" && interventions > 0 && (
                <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-attention live" />
              )}
            </a>
          ))}
        </nav>

        <main className="flex-1 min-w-0 overflow-auto">
          <div className="max-w-[1440px] mx-auto px-6 py-5">{page}</div>
        </main>
      </div>
    </div>
  );
}
