# Hard questions a reviewer will ask, and the answers

This is the decision log behind Glovebox, written as the questions an engineering interviewer
at a bank-automation company would actually ask. Where the honest answer is "that is a gap",
it says so.

## The core loop

**Is the discovery run real?** Yes when `evidence/discovery/` contains a run recorded by
`anthropic:claude-*` (see `capability.json → provenance.model`). Every other evidence bundle
is a replay and needs no model; `discovery-offline-scripted/` is explicitly labelled as a
scripted stand-in and exists only to show the artifact path is model-independent.

**Why a compact element list instead of pure screenshots?** Because actions need an address.
Screenshot-only agents click coordinates, which cannot be recorded into a stable locator.
The element list is what an accessibility API gives you on desktop too, so it is the
surface-agnostic choice. Screenshots are still attached so the model sees layout.

**Why do element refs expire on every observation?** So the model can never act on stale
state after a navigation. A stale ref is a tool error, not a wrong click.

**Why can the model not see credentials?** It references parameters by name; the loop
substitutes the value. This removes a whole class of leaks (transcripts, logs, prompts) at
zero cost to capability quality.

## The artifact

**Why several locator strategies per target instead of the best one?** Because "best" is
unknowable at record time. Each strategy is independent, ordered by expected stability, and
carries the recorder's own note about uniqueness. Replay logs which index resolved, which is
the drift signal.

**Why is ambiguity an error?** Acting on the wrong control in a core banking screen is worse
than stopping. Two matches → stop with expected/observed, or hand to a human.

**Why are business outcomes, recoveries and failure signals separate lists?** Because the
caller needs to branch on outcomes (`MEMBER_NOT_FOUND` is an answer), recoveries need a
bounded scripted response, and failures need evidence. Conflating them is the classic
mistake; making them schema-level forces the reviewer to see the taxonomy.

**Why does the validator refuse `max_risk: reversible` with an irreversible step?** So the
catalog's risk label can be trusted by the agent-facing product without reading steps.

**Why does re-recording bump the patch version and reset review?** Approval attaches to a
specific set of steps. New steps, new review. The version history is the audit trail.

**What is deliberately not in the artifact?** Model messages, raw HTML, timing assumptions,
and coordinates as a primary locator.

## Replay and robustness

**How is determinism actually achieved?** No model; ordered strategies with a uniqueness
check; condition-based waits (load state, then expectations with timeouts); dialogs armed
before the click that raises them; frames addressed by name path; bounded recoveries (max
attempts, max two restarts).

**What happens when the human's fix changes the page state?** `resume` retries the current
step; `restart` re-runs from the entry step. The interstitial test exercises exactly this:
dismissing a modal that reloads the form requires re-entering the field or restarting.

**Text-based outcome detection can false-positive.** True. Detectors are frame-scopable and
part of the reviewed artifact; the mitigation is review, not cleverness. A production
version would also require the detector to be absent on the success screen at record time.

**Why does each replay sign in?** Simplicity. A session-bootstrap capability plus a session
pool is the first cut to restore (REPORT §7).

## Human in the loop

**Is the handoff the same session?** Yes. The automation thread stays alive and executes the
human's commands on the same Playwright page via a thread-safe bridge; cookies, frames and
state are untouched. A fresh browser would have been easier and would have failed the brief.

**Who is in control, at any instant?** `ControlSession.owner`, logged on every transition,
shown as a chip on every run in Studio.

**Why six hand-back verbs?** Resume and restart cover "I cleared it"; complete covers "I
finished it"; abort covers "stop"; approve/decline cover irreversible confirmations. Each maps
to a distinct engine behaviour; fewer verbs would force the human to lie to the system.

**Is the operator authenticated?** No. Studio binds to localhost and trusts the browser. A
real deployment needs SSO, per-tenant authorisation, and an audit identity on every human
action (the `operator` field is already recorded; it is just self-declared today).

## Safety

**Can an approved artifact escape the allowlist?** No. The same `Guardrails` object runs in
front of every action in both discovery and replay.

**What can still leak?** What is on screen: screenshots and DOM snapshots show member names
and balances. Password fields are masked by the browser. Sensitive-field screenshot
suppression and evidence classification are listed cuts.

**Why `confirm` for irreversible actions rather than `block`?** Because opening a sub-account
is the product. `block` would make the system safe and useless; `allow` would make it useful
and dangerous. `confirm` in discovery plus refuse-unattended in replay is the conservative
middle.

## Heterogeneity and scale

**Would this work on a desktop app?** The artifact vocabulary (role, name, label, spatial
anchor, box) is what UIA/AX expose. The `Surface` protocol is the only thing to implement.
That is an argument, not a demonstration; a second surface is the top engineering cut.

**How does one artifact serve hundreds of tenants?** Locator fallthrough absorbs cosmetic
differences; `TenantOverride` patches by step id for the rest (origin, entry, targets,
values, extra recoveries). The committed artifact carries a real override for tenant `bravo`
and the evidence bundle shows it replaying there.

**How is drift detected at fleet scale?** Every step logs which strategy index resolved.
Per-tenant, per-step histograms of that index are the signal; a climbing index is a vendor
upgrade, a single tenant at index 2 is an override candidate. Designed, not built.

## Engineering quality

**Why is the frontend loosely typed while the backend is mypy strict?** Time. The API is the
contract and is typed with Pydantic; the UI consumes JSON with `any` in several places. The
fix is generating TypeScript types from the Pydantic JSON Schema (`docs/capability.schema.json`
already exists). Listed as a cut.

**Why commit built UI assets?** So Python is the only runtime a reviewer needs. CI rebuilds the
UI and fails if the committed assets are stale.

**Why a simulated target rather than a public site?** Reproducible faults. No public site lets
you inject a session expiry or an HTTP 500 on demand, and the brief is explicit that runtime
errors, not layout drift, are the interesting failures.

**What would you do first with another week?** Session reuse; assisted single-step repair
on `target_not_found` (bounded, policy-checked, reviewed before use); fleet drift telemetry;
a UIA surface; operator auth; typed frontend.
