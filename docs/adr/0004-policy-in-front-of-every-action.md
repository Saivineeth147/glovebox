# ADR 0004 — The same guardrails sit in front of the model and the artifact

**Status:** accepted · **Date:** 2026-09-12

## Context
Regulated environment; the agent must never act outside an allowlist, irreversible actions
need conservative handling, and secrets/PII must not be persisted.

## Decision
One `Guardrails` object (allowed origins/paths, denied paths, allowed action kinds, risk
matrix) is consulted before every navigation and action, whether the decision came from the
model (discovery) or from a reviewed artifact (replay). Irreversible steps default to
`confirm`: a human must approve during discovery, and unattended replay is refused.
Capabilities start as `draft` and replay refuses drafts unless explicitly overridden.
Redaction is applied at the evidence boundary: registered secrets (credentials, sensitive
parameters, sensitive outputs) plus pattern rules, before anything is written.

## Consequences
- A wrong artifact cannot escape the allowlist any more than a wrong model decision can.
- Sensitive parameters never reach the model: it references them by name; the loop
  substitutes the value.
- Screenshots may still show what the *screen* shows; the surface masks password fields,
  and PII on screen is the remaining exposure (documented limit, see Glovebox-Design-Writeup.md §6).
