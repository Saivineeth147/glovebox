# Evidence

Every directory is one run: `events.jsonl` (structured, redacted log), `screenshots/`,
`snapshots/` (frame HTML on failure/handoff), `result.json` (replay) or `transcript.json` +
`capability.json` (discovery). Replay bundles also carry `SUMMARY.json` — what was injected and
what came back.

| Bundle | What it shows |
|---|---|
| `discovery/` | **The real LLM-driven discovery run** (Claude Sonnet 5, reached through OpenRouter's
OpenAI-compatible endpoint — see `provenance.model` in `capability.json`) that recorded `capabilities/member_savings_balance.json`. |
| `discovery-offline-scripted/` | The same loop driven by `ScriptedLLM` — no model. Shows the artifact-generation path is model-independent. Clearly not a model run. |
| `replay-success/` | Deterministic replay with a *different* member id; outputs returned. |
| `replay-business-outcome-not-found/` | Unknown member → `business_outcome: MEMBER_NOT_FOUND`, not a failure. |
| `replay-invalid-input/` | Parameter fails its pattern → `failed/input_invalid` before the app is touched. |
| `replay-hard-failure-app-error/` | Injected HTTP 500 → `failed/failure_signal` with screenshot + DOM snapshots. |
| `replay-recovered-session-expired/` | Injected session expiry → declared recovery restarts the flow → success. |
| `replay-recovered-slow-load/` | Injected 4 s delay → absorbed by load-state waits → success. |
| `replay-escalated-handoff-interstitial/` | Undeclared modal → automation stuck → **human takes over the live session** via the operator bridge, clicks OK, hands back → success. See `control.*` events. |
| `replay-unattended-stuck-interstitial/` | Same modal with no human reachable → `failed/target_not_found` with expected/observed and evidence. |
| `replay-tenant-bravo-override/` | Artifact recorded on tenant *alpha* replayed on tenant *bravo* (renamed labels, extra notice) through a `TenantOverride`. |

Regenerate the replay bundles with `make evidence`; regenerate `discovery/` with `make discover`.
