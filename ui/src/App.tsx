import React, { useEffect, useState } from "react";
import { Activity, BookOpen, Compass, LayoutDashboard, ShieldCheck } from "lucide-react";
import Overview from "./pages/Overview";
import Runs from "./pages/Runs";
import RunDetail from "./pages/RunDetail";
import Capabilities from "./pages/Capabilities";
import CapabilityDetail from "./pages/CapabilityDetail";
import Discover from "./pages/Discover";
import Policy from "./pages/Policy";
import SignIn from "./pages/SignIn";
import { api, NotSignedIn } from "./api";

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
  // undefined while we are still asking; null once we know nobody is signed in.
  const [user, setUser] = useState<{ email: string; role: string } | null | undefined>(undefined);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  useEffect(() => {
    if (!user) return;
    const load = () =>
      api
        .overview()
        .then(setOv)
        .catch((e) => (e instanceof NotSignedIn ? setUser(null) : setOv({ target: { up: false } })));
    load();
    const timer = setInterval(load, OVERVIEW_POLL_MS);
    return () => clearInterval(timer);
  }, [user]);

  if (user === undefined) return <div className="h-full" />;
  if (user === null) return <SignIn onSignedIn={setUser} />;

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
      <header className="h-band shrink-0 flex items-center gap-5 px-5 border-b border-ink-800/80 bg-ink-950/70 backdrop-blur">
        <a href="#/" className="flex items-baseline gap-2 shrink-0">
          <span className="text-[14px] font-semibold tracking-[0.16em] text-ink-100">GLOVEBOX</span>
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
          <span className="flex items-center gap-2 whitespace-nowrap border-l border-ink-700 pl-4">
            <span className="text-ink-200">{user.email}</span>
            <span className="text-ink-400">{user.role}</span>
            <button
              type="button"
              className="text-ink-400 hover:text-ink-100"
              onClick={() => api.signOut().then(() => setUser(null))}
            >
              Sign out
            </button>
          </span>
        </div>
      </header>

      <div className="flex-1 min-h-0 flex">
        <nav
          aria-label="Sections"
          className="w-rail shrink-0 border-r border-ink-800/80 bg-ink-950/40 flex flex-col items-center py-3 gap-1.5"
        >
          {NAV.map(({ path, label, icon: Icon }) => (
            <a
              key={path}
              href={`#${path}`}
              title={label}
              aria-current={isActive(path) ? "page" : undefined}
              className={`relative w-11 h-11 grid place-items-center rounded-port transition-colors
                focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink-200/40 ${
                  isActive(path)
                    ? "bg-ink-800 text-ink-100 border border-ink-600/70"
                    : "text-ink-500 hover:bg-ink-850 hover:text-ink-200"
                }`}
            >
              <Icon className="w-[18px] h-[18px]" strokeWidth={1.75} />
              <span className="sr-only">{label}</span>
              {path === "/runs" && interventions > 0 && (
                <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-attention live" />
              )}
            </a>
          ))}
        </nav>

        <main className="flex-1 min-w-0 overflow-auto">
          <div className="max-w-[1320px] mx-auto px-8 py-8">{page}</div>
        </main>
      </div>
    </div>
  );
}
