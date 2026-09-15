# Contributing

```bash
make setup && make lint && make test
```

- `src/glovebox/schema/` is the contract. A change there needs a schema-version bump when it is
  not backward compatible, a test in `tests/unit/test_schema.py`, and a note in REPORT.md §2.
- New surface implementations implement `glovebox.surface.base.Surface`; nothing above the
  surface should need to change. Add a `TargetStrategy.kind` only if a surface can resolve it.
- Every runtime condition the replay engine handles must have an integration test that injects
  it through the simulator's fault switchboard (`/__sim/faults/<name>`), and an evidence bundle
  (`make evidence`).
- Never commit `.env`, `runs/`, or anything under `evidence/` that has not been through the
  redactor. CI validates committed artifacts with `glovebox validate`.
- Decisions with trade-offs go in `docs/adr/` as a short ADR.
