# ADR 0002 — Business outcomes, recoveries and failures are three different things

**Status:** accepted · **Date:** 2026-09-12

## Context
"No such member" is a legitimate answer. A "System notice" modal is noise to dismiss. An
HTTP 500 is a defect. Collapsing these into one "error" makes the capability useless to the
calling agent and un-debuggable to the engineer.

## Decision
The artifact declares three separate lists, and the replay engine evaluates them in a fixed
order after every step: `failure_signals` (stop, capture evidence, `failed`), `outcomes`
(stop, `business_outcome` with a code the agent can branch on), then step `expect`ations;
if an expectation fails, `recoveries` whose detector fires run a bounded scripted response
(`retry_step` / `continue` / `restart_capability` / `escalate`). Anything left is "stuck":
an intervention when a human is reachable, a `failed` result with expected/observed and
evidence when not.

## Consequences
- The result contract has four statuses; callers never parse messages to know what happened.
- Recoveries are bounded (`max_attempts`, at most two restarts) so replay cannot loop.
- Discovery encourages the model to declare outcomes it can infer from the UI, and a reviewer
  can add more before approval — the taxonomy is part of the reviewable artifact.
