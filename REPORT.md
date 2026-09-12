# Glovebox — Design write-up

Glovebox turns one LLM-driven run against a legacy bank application into a deterministic,
reviewable capability that an AI agent invokes in production without the model. This document
explains the shape of the system and the decisions behind it. Code references are to
`src/glovebox/`.

## 1. Architecture

**One process, four layers, two seams.**

```
                    ┌────────────────────────────┐
  discovery         │  agent/loop.py  (model)     │      replay/engine.py (no model)
  goal + params ───▶│  observe → decide → act     │      capability + params ──▶ result
                    └──────────┬─────────────────┘                 │
                               │ every action                       │ every step
                    ┌──────────▼─────────────────────────────────────▼──────────┐
                    │  policy/guardrails.py   allowlist · action kinds · risk     │
                    ├────────────────────────────────────────────────────────────┤
                    │  control/session.py     lease: automation ⇄ human           │
                    ├────────────────────────────────────────────────────────────┤
                    │  surface/  (Surface protocol)  observe · act · resolve      │  ◀── seam 1
                    │     web/playwright_surface.py + walker.js + locators.py     │
                    └────────────────────────────────────────────────────────────┘
                               │ events, screenshots, snapshots (redacted)
                    ┌──────────▼─────────────────┐   ┌───────────────────────────┐
                    │  evidence/  runs/<run_id>/  │   │ schema/capability.py       │  ◀── seam 2
                    └────────────────────────────┘   │ the artifact both paths use │
                                                     └───────────────────────────┘
```

*Seam 1* is the surface: the only code that knows Playwright. It exposes elements the way an
operator perceives them (role, name, label, text, frame, box) and resolves recorded targets.
*Seam 2* is the artifact: discovery writes it, humans review it, replay reads it; nothing in it
refers to the model transcript.

Key decisions and trade-offs:

- **Discovery and replay share the guardrails, surface and evidence code.** The model's
  decisions and a reviewed artifact go through the same `Guardrails` and the same
  `Surface.click/fill`. A capability therefore cannot do anything during replay that policy
  would have refused during discovery, and replay fidelity is structural, not hoped for.
- **Perception is a compact element list with ephemeral refs, not raw DOM.** The walker
  (`surface/web/walker.js`) runs per frame and emits ~50–150 lines of "[e12] textbox
  'Member No.' name=member_no frame=main". The model acts on refs; refs expire on every
  observation, so it can never act on stale state. Screenshots are attached when requested or
  by default for discovery, so the model also *sees* the screen; the text is what makes actions
  addressable. This is the bias the brief asks for: the same vocabulary works when there is no
  clean DOM, because it is what an accessibility tree provides.
- **Single process, synchronous.** A run is one browser, one thread. Queues, workers and a
  service boundary are deliberate non-goals (brief §7); the seams are where they would go
  (`runner.py` is the unit of work a queue would dispatch; `studio/jobs.py` already runs each
  job on its own thread with its own bridge, which is the shape a worker pool would keep).
- **Studio is a client, not a second implementation.** The workspace UI (`studio/`, `ui/`)
  reads the same `events.jsonl` every run writes, streams it over SSE for live views, and
  drives takeover through the same `OperatorBridge` verbs the CLI console uses. Nothing in
  the UI can do what the CLI cannot; it makes the control model and the evidence visible.
- **Model boundary is a protocol.** `AnthropicLLM` (Claude Sonnet 5 by default via the Anthropic SDK,
  adaptive thinking, prompt caching on the frozen system prompt, streaming), `OpenAICompatibleLLM`
  (OpenRouter or OpenAI, with tool-call translation) and `ScriptedLLM`
  produce identical tool-call shapes. Every test and every replay evidence bundle runs offline;
  the one thing that must be real — the discovery run — is (see `evidence/discovery/`).
- **The target is a purpose-built hostile app** rather than a public demo site: framesets,
  table layouts, no ids, native `confirm()`, two tenants, and an injectable fault switchboard.
  A public site cannot give us a reproducible session expiry or HTTP 500.

## 2. Artifact schema

`schema/capability.py` (JSON Schema via `glovebox schema`; example: `capabilities/member_savings_balance.json`).

```
Capability
  id, version (semver), title, description          ← identity, human-readable
  app: {app_id, vendor_version, tenant, origin, entry_path}
  inputs:  [Parameter{name, type, description, required, pattern, enum, sensitive}]
  outputs: [OutputSpec{name, type, description, sensitive}]
  steps:   [Step{id, action, intent, target?, value?, wait, risk, expect[], extract_to?, dialog_response?}]
  success: [Condition]            ← terminal checkpoint
  outcomes:        [Outcome{code, description, detect}]      ← legitimate non-success results
  recoveries:      [Recovery{name, detect, actions[], then, max_attempts}]
  failure_signals: [Condition]                               ← stop now
  max_risk, provenance{discovery_run_id, model, transcript_sha256, …}, review{status, confidence…}
  overrides: [TenantOverride{tenant, origin, entry_path, step_targets{}, step_values{}, extra_recoveries[]}]
```

Why this shape:

- **It is a contract first.** `inputs`/`outputs`/`outcomes`/`success` are what a calling agent
  needs; `catalog/registry.py` derives a Claude tool definition from them directly (name, typed
  `input_schema`, description listing outputs and outcome codes). `steps` are for the engine
  and the reviewer.
- **Targets carry their own robustness argument.** A `Target` is a description plus an
  ordered list of independent `TargetStrategy` entries, each with a `robustness` note the
  recorder writes from what it observed (e.g. "NOT unique at record time"). A reviewer can
  read why a step should survive; the engine logs which strategy actually resolved. Data cells
  are located by *row anchor + column header* (`table_cell`) or "cell right of label"
  (`near_text`), never by their value, so extraction is input-independent.
- **Values are templates.** `{{ params.member_id }}`; the schema rejects references to
  undeclared inputs and outputs that are never extracted. Sensitive parameters are declared
  as such and never appear in the artifact.
- **Risk is declared per step and rolled up.** The validator refuses a capability that claims
  `max_risk: reversible` while containing an irreversible step, so the catalog's risk label is
  trustworthy.
- **Three non-happy-path lists** (ADR 0002) make the error taxonomy part of the reviewable
  artifact rather than engine heuristics.
- **Provenance + review + overrides** make it versioned and reviewable: who/what recorded it
  (hash of the redacted transcript, not the transcript), whether a human approved it, how
  often it has replayed successfully, and how it is specialised per tenant.

What I chose *not* to put in it: model messages, raw HTML, absolute coordinates as a primary
locator (allowed only as a last-resort strategy), and per-step timing assumptions beyond a
`WaitSpec`.

## 3. Determinism & error handling

**Determinism.** Replay (`replay/engine.py`) never consults a model. For each step:
policy check → resolve target (first strategy that matches exactly one visible element; two
matches is an error, not a guess) → act → wait for load state + settle → classify. Waits are
condition-based (load state, then expectations with a timeout) rather than sleeps; the
`slow` fault (4 s server delay) passes without any special handling. Native dialogs are
declared ahead of time (`expect_dialog`) so the handler is armed before the click that raises
it. Frames are addressed by name path. Stability can be measured: `glovebox stability --runs N`.

**Runtime errors and exceptional states** are classified in a fixed order after every step:

| Observed | Class | Engine response | Result |
|---|---|---|---|
| HTTP 5xx, "Application Error" | `failure_signals` | stop; screenshot + per-frame DOM snapshot | `failed / failure_signal` |
| "No member record matched", "Access denied", validation message | `outcomes` | stop | `business_outcome / <CODE>` |
| Session expired | `recoveries` (`restart_capability`, max 2) | re-run from the entry step (re-login) | `success` (steps show `recovered`) |
| Declared interstitial | `recoveries` (`retry_step`) | click the declared dismiss control, retry | `success` |
| Undeclared modal / target missing | none matched → *stuck* | attended: intervention; else stop | `escalated` or `failed / target_not_found` |
| Post-condition not met | step `expect` | recoveries, then stuck | as above, `checkpoint_failed` |
| Bad parameter | input contract | refuse before touching the app | `failed / input_invalid` |
| Draft artifact, disallowed action/URL | policy | refuse | `failed / not_approved`, `policy_violation` |

The **result contract** (`schema/results.py`) has four statuses — `success`, `business_outcome`,
`escalated`, `failed` — and a `Failure{failure_class, step_id, message, expected, observed,
evidence{}}`. Every row above is exercised by `tests/integration/test_end_to_end.py` and has an
evidence bundle.

**UI drift** (secondary here): the strategy fallthrough absorbs a renamed label or moved
element and *records* that it did (`replay.target.resolved … via name_attr#2`), which is the
drift signal a maintainer needs. Unresolvable targets fail loudly with expected/observed.

### What determinism buys

Measured across the discovery and replay runs in this repository's `runs/` directory, on
`openrouter:anthropic/claude-sonnet-5` at $2/$10 per million tokens:

| | discovery | replay |
|---|---|---|
| model in the loop | yes | **no** |
| median wall clock | 86.4 s | **2.8 s** |
| median input tokens | 83,195 | **0** |
| median output tokens | 3,390 | **0** |
| cost per run | ~$0.20 | **$0.00** |
| how often it runs | once per capability, plus a re-record on drift | every transaction |

The ratio is the argument for the whole design. A capability recorded once for twenty cents
runs for nothing thereafter, at thirty times the speed, with the same answer every time — and
the thing an auditor reads is a reviewed JSON contract rather than a model transcript. Putting
the model in the production path would invert all four rows and none of the guarantees.

The figures are medians over 6 successful discovery runs and 26 successful replays; discovery
cost varies with how much the model explores, which §7's discovery quality loop is partly
about controlling.

## 4. Heterogeneity & multi-tenant

**Surface abstraction.** `surface/base.py` defines `Surface` with nine verbs (`observe`,
`navigate`, `click`, `fill`, `select`, `press`, `arm_dialog`, `resolve`, `check`, plus
`capture`). `Element` deliberately uses accessibility vocabulary — role, name, label, text,
frame path, bounding box — and `TargetStrategy.kind` is a closed set that a non-DOM surface can
implement: a Windows UIA or macOS AX surface maps `role_name`/`label`/`near_text`/`bbox` onto
its tree; a pure screenshot surface implements `bbox` and `text` (via OCR) and reports the
others as unsupported. `css`/`name_attr` are web-only and simply never match elsewhere. The
artifact, the engine, the policy and the control model do not change. What *is* web-specific
today: the walker, the CSS structural path, and Playwright's dialog/response hooks.

**Multi-tenant reuse.** The same vendor product configured per institution is handled at
three levels, none of which require re-recording:

1. *Locator fallthrough* absorbs cosmetic differences for free. Tenant "bravo" renames
   "Member No." → "Member Number" and "Find Member" → "Search"; replay resolves through the
   server-bound `name_attr` and logs it (`evidence/replay-tenant-bravo-override/`).
2. *`TenantOverride`* specialises what fallthrough cannot: a different origin or entry path,
   a replaced target or value for a named step, and extra recoveries (bravo's post-login
   maintenance notice). Overrides are additive patches by step id, so the base flow remains
   the single source of truth and a reviewer sees exactly what differs per institution.
3. *App identity* (`app.app_id`, `vendor_version`) is separate from tenant, so a fleet catalog
   is keyed by product and version, with tenant overlays.

**Detecting and managing drift** at fleet scale, as designed (not built): every replay emits
which strategy index resolved each step; a per-tenant, per-step histogram of strategy index
is the drift signal — index 0 everywhere is healthy, a tenant whose step 8 consistently needs
index 2 is a candidate for an override, a tenant where index climbs over time is a vendor
upgrade. Failures with `target_not_found` on one tenant only should open an intervention whose
recorded human actions are proposed as that tenant's override (the loop already folds human
actions into steps during discovery). Confidence (`review.replays/successes`) is tracked per
artifact today and would be tracked per (artifact, tenant) in the fleet store.

## 5. Escalation & handoff

**Detecting "stuck".** Four triggers, all first-class: (a) the model calls `escalate` during
discovery; (b) the discovery loop sees no screen change across four consecutive actions;
(c) replay cannot resolve a target or an expectation fails and no recovery matches;
(d) a step is `irreversible` and policy says `confirm`. Policy blocks are a fifth route
(`blocked`) reserved for a future "human overrides policy" flow — today they fail closed.

**Routing with context.** An `Intervention` carries run id, capability/goal, step id, reason,
current URL, a fresh screenshot, and the rendered observation, and is logged as an event
(`control.intervention`). The console shows exactly this.

**Taking control of the live session** (ADR 0003). `ControlSession` holds a lease:
`automation` or `human`. Raising an intervention transfers the lease and, crucially, does not
exit the run: the automation thread stays alive *serving* the human. `OperatorBridge` is a
thread-safe mailbox; the console (or a scripted operator) submits `observe/click/fill/select/
press/navigate`, and the automation thread executes them on the same Playwright page — same
cookies, same frames, same state. Each human action is recorded as `control.human_action`
with the same multi-strategy target description the recorder uses, plus screenshots before and
after.

**Handing back.** Six terminal verbs: `resume` (retry the current step — the engine
re-evaluates the expectation, so if the human cleared the obstacle the run continues),
`restart` (re-run the flow from the entry step, bounded; for when the human's fix reset
intermediate state such as a form), `complete` (the human finished the flow; the engine
verifies `success` and runs the extraction steps so the caller still gets outputs), `abort`,
and for confirmations `approve`/`decline`.
A handoff has a timeout; expiry returns the lease and the run ends `escalated / timed_out`
rather than pinning a worker. The evidence for both directions is in
`evidence/replay-escalated-handoff-interstitial/` and the console path is tested over HTTP.

**Who is in control** is always answerable: `ControlSession.owner`, the `control.transition`
events, and the owner chip on every run in Studio.

**The operator's surface** (Studio, run page) shows the intervention with its reason, step,
capability and what the automation saw; the live session as a screenshot with a clickable
hotspot for every interactive element (drawn from the same element list the model sees, so
the human and the model literally share a perception); an action bar; the hand-back verbs
with one-line explanations; and the human's own actions as they are recorded. A stuck run
is a purple banner at the top of its page, and open interventions are counted in the sidebar.

What a production console adds on the same seam: a screencast (CDP `Page.screencast` or VNC
to a headed browser) instead of polled screenshots, operator identity/authorisation, and a
queue of interventions across runs. None of that changes the bridge verbs.

## 6. Safety

**Allowlist** (`policies/default.yaml`, enforced by `policy/guardrails.py`): exact origins,
allowed path regexes, denied path regexes (the simulator's fault endpoints and the logout
route are denied even though they are on the allowed origin), allowed action kinds. Checked
before every navigation and action in both discovery and replay; the model is told the
policy exists and sees the refusal as a tool error.

**Risk classes.** Every step carries `read | reversible | irreversible`; the model must
declare `irreversible` on clicks that commit business changes and the recorder rolls the
maximum up into the artifact. Policy `irreversible_policy: confirm` means: during discovery a
human approves each irreversible action through the same handoff mechanism; unattended replay
of an irreversible capability is refused (`policy_violation`) and attended replay asks for
approval at the step. I chose "confirm" over "block" because sub-account opening is exactly
the kind of capability the product needs; over "allow" because a wrongly recorded step would
otherwise commit changes silently.

**Secrets and PII.** Sensitive parameters are referenced by name in the model's tool calls;
the loop substitutes the value, so credentials never enter the transcript. The `Redactor`
replaces registered secrets (credentials, sensitive inputs and outputs) with a labelled,
run-stable fingerprint and applies pattern rules (API keys, bearer tokens, card PANs, SSNs,
`password=`, session cookies) to every event, transcript and artifact before it is written.
Approval gating (`draft` → `approved`) keeps unreviewed automation out of production.

**Limits, stated plainly.** Screenshots show what is on screen; password fields are masked
by the browser, but member names and balances are visible in evidence images and DOM
snapshots. In production, evidence would be classified and stored under the same controls as
the source system, with configurable screenshot suppression for fields tagged sensitive. The
allowlist is URL-based; an in-app action that mutates without changing the URL relies on the
declared risk class. Text-based outcome detection can false-positive if a page legitimately
contains the detector string; detectors should be scoped to a frame (supported) and reviewed.
Redaction of free text is best-effort; structured sensitivity flags are the reliable mechanism.

## 7. Cuts

Cut deliberately, in order of what I would build next:

1. **Session reuse.** Each replay signs in; a session-bootstrap capability plus a per-tenant
   session pool would remove ~2 s per run and keep credentials out of the main flow entirely.
2. **Assisted repair.** On `target_not_found`, a bounded, policy-checked single-step model
   call that proposes a new `TargetStrategy` for review (never executes unreviewed), and the
   human-action → override proposal described in §4.
3. **Fleet drift telemetry** (§4): strategy-index histograms per tenant/step, confidence per
   (artifact, tenant), automatic override suggestions.
4. **A second surface** (Windows UIA or macOS AX) to prove the seam with code rather than
   argument. The walker's element model was written with `pywinauto`/`atspi` trees in mind.
5. **Console hardening:** screencast instead of polling, operator auth, intervention queue,
   and recording the human's actions as a *patch proposal* to the artifact.
6. **Sensitive-field screenshot suppression** and evidence retention policy.
7. **Discovery quality loop:** run discovery twice and diff the artifacts; prefer steps with
   more independent strategies; auto-suggest `assert_text` checkpoints where the model forgot.
8. **Operator authentication and audit identity.** Studio binds to localhost and trusts the
   browser; the `operator` name on every human action is self-declared. Production needs SSO
   and per-tenant authorisation on the takeover endpoints.
9. **Typed frontend.** The API is Pydantic-typed; the React client consumes JSON loosely.
   Generate TypeScript types from `docs/capability.schema.json` and the result contract.

The reviewer-facing decision log, including the questions I expect to be asked and the
honest answers, is in [docs/hard-questions.md](./docs/hard-questions.md).

Not cut, but thin on purpose: the operator UI (mechanism is real, pixels are minimal), and
the target app (hostile enough to matter, not a full core banking system).
