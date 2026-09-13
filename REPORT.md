# Glovebox — Design write-up

Glovebox turns one LLM-driven run against a legacy bank application into a deterministic,
reviewable capability that an AI agent invokes in production without the model. Code references
are to `src/glovebox/`; the reviewer-facing decision log is `docs/hard-questions.md`.

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
                    │     web/ (Playwright)     http/ (no browser)               │
                    └────────────────────────────────────────────────────────────┘
                               │ events, screenshots, snapshots (redacted)
                    ┌──────────▼─────────────────┐   ┌───────────────────────────┐
                    │  evidence/  runs/<run_id>/  │   │ schema/capability.py       │  ◀── seam 2
                    └────────────────────────────┘   │ the artifact both paths use │
                                                     └───────────────────────────┘
```

*Seam 1* is the surface: the only code that knows how a screen is reached. It exposes elements
the way an operator perceives them — role, name, label, text, frame, box — and resolves recorded
targets. *Seam 2* is the artifact: discovery writes it, humans review it, replay reads it, and
nothing in it refers to the model transcript.

- **Discovery and replay share the guardrails, surface and evidence code.** A capability cannot
  do anything on replay that policy would have refused during discovery; fidelity is structural.
- **Perception is a compact element list with ephemeral refs, not raw DOM.** The model acts on
  refs that expire on every observation, so it can never act on stale state. Screenshots are
  attached so it also *sees* the screen; the text is what makes actions addressable, and it is
  the vocabulary an accessibility tree provides when there is no clean DOM.
- **Single process, synchronous.** Queues and a service boundary are deliberate non-goals;
  `runner.py` is the unit of work a queue would dispatch.
- **The model boundary is a protocol.** Anthropic direct, any OpenAI-compatible endpoint, and a
  scripted stand-in produce identical tool-call shapes, so every test runs offline and the one
  thing that must be real — the discovery run in `evidence/discovery/` — is.
- **The target is a purpose-built hostile app**: framesets, table layouts, no ids, native
  `confirm()`, two tenants, injectable runtime faults, and injectable *structural* redesigns. A
  public site cannot give a reproducible session expiry, HTTP 500, or renamed control.
- **Studio is a client, not a second implementation.** It reads the same `events.jsonl` every
  run writes and drives takeover through the same bridge verbs the CLI console uses.

## 2. Artifact schema

`schema/capability.py`; JSON Schema via `glovebox schema`; example `capabilities/member_savings_balance.json`.

```
Capability
  id, version (semver), title, description
  app: {app_id, vendor_version, tenant, origin, entry_path}
  inputs:  [Parameter{name, type, description, required, pattern, enum, sensitive}]
  outputs: [OutputSpec{name, type, description, sensitive}]
  steps:   [Step{id, action, intent, target?, value?, wait, risk, expect[], extract_to?}]
  success: [Condition]                                       ← terminal checkpoint
  outcomes:        [Outcome{code, description, detect, terminal, verified}]
  recoveries:      [Recovery{name, detect, actions[], then, max_attempts}]
  failure_signals: [Condition]
  max_risk, provenance{discovery_run_id, model, transcript_sha256}, review{status, reviewed_by, …}
  overrides: [TenantOverride{tenant, origin, entry_path, step_targets{}, step_values{}, extra_recoveries[]}]
```

- **It is a contract first.** `inputs`/`outputs`/`outcomes`/`success` are what a calling agent
  needs, and `catalog/registry.py` derives a tool definition from them directly. `steps` are for
  the engine and the reviewer.
- **Targets carry their own robustness argument.** A `Target` is an ordered list of independent
  strategies (`role_name`, `label`, `name_attr`, `text`, `near_text`, `table_cell`, `css`, `bbox`),
  each with the recorder's note on uniqueness. Data cells are addressed by row anchor and column
  header, never by their value, so extraction is input-independent.
- **Values are templates**, so the schema can reject references to undeclared inputs and
  outputs never extracted; sensitive parameters never appear in the artifact.
- **Risk is per step and rolled up**; the validator refuses `max_risk: reversible` on a flow with
  an irreversible step, so the catalog's label can be trusted.
- **Three non-happy-path lists** make the error taxonomy part of the reviewed artifact rather
  than engine heuristics (ADR 0002).
- **`verified` on an outcome** records whether its detector text was actually observed during the
  run. The model will otherwise guess wording it never saw, and a guessed detector never fires.

What I kept out: model messages, raw HTML, coordinates as a primary locator, timing assumptions.

## 3. Determinism & error handling

**Determinism.** Replay never consults a model. For each step: policy check → resolve the first
strategy that matches *exactly one* visible element (two matches is an error, not a guess) → act →
wait for load state and settle → classify. Waits are condition-based, not sleeps; dialogs are armed
before the click that raises them; frames are addressed by name path.

**Runtime errors and exceptional states** are classified in a fixed order after every step:

| Observed | Class | Result |
|---|---|---|
| HTTP 5xx, "Application Error" | `failure_signals` | `failed / failure_signal` + screenshot, DOM snapshot |
| "No member record matched", "Access denied" | `outcomes` | `business_outcome / <CODE>` |
| Session expired | `recoveries` → restart from entry, max 2 | `success`, steps marked `recovered` |
| Declared interstitial | `recoveries` → dismiss, retry | `success` |
| Undeclared modal, target missing | nothing matched → *stuck* | attended: `escalated`; else `failed` |
| Extracted text without the recorded shape | checkpoint | `failed / checkpoint_failed`, expected vs observed |
| Bad parameter · draft artifact · disallowed URL | contract · policy | refused before touching the app |

The result contract has four statuses — `success`, `business_outcome`, `escalated`, `failed` — and
a `Failure{failure_class, step_id, expected, observed, evidence}`. Every row has an integration
test and an evidence bundle.

**What the discovery run must not record.** The first live run produced an artifact that
validated and did not work: it had baked the recorded member's balance into `success` and declared
the happy path as a terminal outcome, so replay ended before extraction. The recorder now refuses,
as a *retryable tool error* the model can act on, any condition built from run data, an outcome
that fires on the success screen, an extraction whose regex misses its element, and a detector the
run never saw — the same mechanism an expired element ref uses. Six live runs converged from a
capability that worked for one member to one that replays for every member and returns
`MEMBER_NOT_FOUND` for a missing one.

**UI drift is measured, not asserted.** `glovebox drift` rewrites the target's rendered pages the
way a redesign would — rename the search control, rename the field label, swap two table columns,
wrap every table, insert a table ahead of the content — and replays every approved capability
against each, reporting which strategy caught each fall. Both capabilities survive all five; CI
fails if that changes. Replay costs 2.8 s and no tokens against 86 s and ~$0.20 for discovery.

## 4. Heterogeneity & multi-tenant

**Surface abstraction, tested rather than argued.** `Surface` has nine verbs and `Element` uses
accessibility vocabulary, so a Windows UIA or macOS AX surface maps `role_name`/`label`/`near_text`
onto its tree and a screenshot surface implements `bbox` and OCR `text`. To prove the seam I built
`surface/http/`: no DOM, no JavaScript, no layout engine, driving the app the way a terminal-era
client would. **The same reviewed capability replays through it in 0.03 s.** Writing it found two
resolver defects — `near_text` returned a confidently wrong element when nothing had been laid out,
and `table_cell` treated the recorded table path as an identity where a parser sees no `<tbody>`.
Both are fixed; both would have shipped otherwise.

**Multi-tenant reuse** happens at three levels, none needing a re-record: locator fallthrough
absorbs cosmetic differences (tenant *bravo* renames two controls; replay resolves through
`name_attr` and logs it); `TenantOverride` patches by step id what fallthrough cannot — origin,
entry path, a replaced target, an extra interstitial recovery — so the base flow stays the single
source of truth; and app identity is separate from tenant, so a fleet catalog is keyed by product
and version with tenant overlays.

**Drift at fleet scale**, designed but not built: the strategy index that resolved each step, kept
per tenant and per step, is the signal. Index 0 everywhere is healthy; a tenant whose step 8 needs
index 2 wants an override; an index climbing over time is a vendor upgrade.

## 5. Escalation & handoff

**Detecting "stuck"**: the model calls `escalate`; the loop sees no screen change over four
actions; replay cannot resolve a target or an expectation fails with no matching recovery; a step
is `irreversible` under `confirm` policy.

**Routing with context.** An `Intervention` carries run, capability, step, reason, URL, a fresh
screenshot and the rendered observation, and is logged as an event.

**Taking control of the live session** (ADR 0003). `ControlSession` holds a lease, `automation` or
`human`. An intervention transfers it without exiting the run: the automation thread stays alive
*serving* the human, executing `observe/click/fill/select/press/navigate` from a thread-safe
bridge on the same page — same cookies, frames and state. Each human action is recorded with the
same multi-strategy target description the recorder uses.

**Handing back.** Six verbs: `resume` retries the current step; `restart` re-runs from the entry
step for when the human's fix reset a form; `complete` verifies `success` and runs the extractions
so the caller still gets outputs; `abort`; and `approve`/`decline` for confirmations. A handoff has
a timeout, and who holds the lease is always answerable from `ControlSession.owner`.

**Identity.** The operator on every recorded action and the reviewer on every approval come from
an authenticated session, not from a name the browser typed. The brief allows the console to be
mocked; I built sign-in because a self-declared identity on an audit trail is not an audit trail.

## 6. Safety

**Allowlist**: exact origins, allowed and denied path patterns (the simulator's fault endpoints
are denied even on the allowed origin), allowed action kinds — checked before every action in both
paths, with refusals returned to the model as tool errors.

**Risk classes.** Each step is `read | reversible | irreversible`, rolled up into the artifact.
Under `irreversible_policy: confirm`, discovery asks a human through the same handoff mechanism,
and unattended replay of an irreversible capability is refused. "Confirm" over "block" because
sub-account opening is exactly what the product must do; over "allow" because a wrongly recorded
step would commit silently.

**Secrets and PII.** The model references sensitive parameters by name and the loop substitutes
the value, so credentials never enter the transcript. A `Redactor` replaces registered secrets with
run-stable fingerprints and applies pattern rules to every event, transcript and artifact before it
is written. Approval (`draft → approved`) gates unattended replay and refuses an outcome whose
detector was never observed unless a reviewer accepts it on the record.

**Limits.** Member names and balances are visible in screenshots and DOM snapshots; production
evidence needs the source system's controls and screenshot suppression for tagged fields. The
allowlist is URL-based, so an in-app mutation that leaves the URL alone relies on the declared risk
class. Redaction of free text is best-effort; structured sensitivity flags are the reliable path.

## 7. Cuts

Deliberately left out, in the order I would build them:

1. **A per-tenant session pool.** Replay can already resume into a warm session with no
   credentials at all; the pool that keeps one warm per tenant is the remaining piece.
2. **Fleet drift telemetry** (§4) and turning a human's recorded takeover actions into a proposed
   tenant override.
3. **Windows UIA surface.** The HTTP surface proves the seam; UIA is the production second surface.
4. **Sensitive-field screenshot suppression** and evidence retention.
5. **A typed frontend** generated from the JSON Schema; the React client consumes JSON loosely.

The one place I deliberately overshot the brief is the operator console, which §3.6 permits
mocking. The control model is the hardest claim here to believe from prose — a human taking the
*same* live session, the automation thread staying alive to serve them — and a working takeover
argues it better. The load-bearing work is still `agent/`, `replay/`, `schema/` and `surface/`.

Of the optional stretch items, I built those that land on a graded axis — approval gating and
stability (safety, robustness), a bounded repair *proposal* that is never applied (robustness),
cross-tenant overrides (generalization), the agent-facing catalog — and skipped code generation.
The recorder guards, the drift evaluation and the browser-free surface were not on the list; each
exists because a real run showed the argument it replaced was wrong.
