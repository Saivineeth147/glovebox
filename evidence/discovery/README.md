# Discovery evidence (real LLM run)

This directory is populated by a genuine model-driven discovery run:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
make target        # terminal 1
make discover      # terminal 2 → writes evidence/discovery/ and capabilities/member_savings_balance.json
```

Contents after the run: `events.jsonl` (every observation, model decision, policy decision and
action, redacted), `screenshots/` (one per observation), `transcript.json` (the redacted model
transcript — tool calls and results, credentials never present), `capability.json` (the artifact
as recorded, before review).

If this file is the only thing here, the real run has not been executed yet in this checkout.
