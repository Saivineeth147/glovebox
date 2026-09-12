# ADR 0001 — Perceive like an operator; locate by ranked, independent strategies

**Status:** accepted · **Date:** 2026-09-12

## Context
Target apps are legacy: framesets, table layouts, no ids or test ids, and sometimes no DOM at
all (desktop). A single CSS/XPath selector recorded at discovery time is exactly what breaks
next month and never transfers to a desktop surface.

## Decision
The surface exposes *elements as an operator perceives them*: role, accessible name, visible
label (computed from table adjacency when there is no `<label>`), text, form `name`, frame
path, bounding box. The recorder derives a `Target` with several **independent** strategies
in a fixed robustness order (role+name → label → name attribute → text → spatial anchor /
table geometry → structural CSS → normalized position). Replay tries them in order and
accepts a strategy only if it matches **exactly one** visible element.

## Consequences
- Drift in one property (a renamed label) is absorbed by the next strategy; the run log
  records which one was used, so drift is observable, not silent (tenant "bravo" test).
- Ambiguity stops the run instead of guessing — acting on the wrong control in a core
  banking screen is worse than escalating.
- Data cells are located by row label + column header, never by their value, so extraction
  works for any member.
- The vocabulary (role/name/label/bbox) is what accessibility APIs expose on desktop, so the
  artifact does not change when the surface does; only the resolver does.
