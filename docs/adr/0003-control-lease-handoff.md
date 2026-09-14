# ADR 0003 — Human handoff is a control lease on the same live session

**Status:** accepted · **Date:** 2026-09-12

## Context
The brief requires a human to take over the *same* session, act, and hand back, with
evidence preserved and the human's actions recorded. Playwright's sync API is single-threaded.

## Decision
`ControlSession` holds a lease (`automation` | `human`) with logged transitions. When
automation raises an intervention it does not exit — it *serves* the human: operator
commands arrive through a thread-safe `OperatorBridge` and are executed on the automation
thread against the same page. Terminal commands (`resume`, `restart`, `complete`, `abort`,
`approve`, `decline`) return the lease. Every human action is recorded with the same multi-strategy
target description the recorder uses. The console is a thin HTTP/HTML client of the bridge.

## Consequences
- One session, one thread, no re-login, cookies/state preserved across the handoff.
- The bridge is the seam: the mock console, the scripted operator used in tests, and a
  future real operator console (WebRTC/VNC/CDP screencast) all speak the same six verbs.
- A handoff times out into an `escalated` result rather than hanging a worker forever.
- The human's recorded actions can later be folded into the artifact (the discovery loop
  already does this) — the first step toward "human-assisted repair" of drifted capabilities.
