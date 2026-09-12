# Glovebox developer entry points. Every target is safe to run offline except `discover`.
.DEFAULT_GOAL := help
UV ?= uv
RUN := $(UV) run

help: ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

setup: ## install deps (uses the system Chromium if PLAYWRIGHT_BROWSERS_PATH is set)
	$(UV) sync --extra dev
	$(RUN) playwright install chromium || true

lint: ## ruff + mypy
	$(RUN) ruff check .
	$(RUN) ruff format --check .
	$(RUN) mypy

fmt: ## auto-format
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

test: ## unit + integration tests (headless browser, local target app)
	$(RUN) pytest

target: ## run the hostile legacy target app on :8089
	$(RUN) glovebox target serve --port 8089

discover: ## real LLM-driven discovery run (needs ANTHROPIC_API_KEY)
	$(RUN) glovebox discover --goal "Look up member 100234 and read their current savings balance" \
		--app-url http://127.0.0.1:8089/ --capability-name member_savings_balance --evidence-dir evidence/discovery

replay: ## deterministic replay of the saved capability
	$(RUN) glovebox replay capabilities/member_savings_balance.json --param member_id=100234 --evidence-dir evidence/replay-success

evidence: ## regenerate every replay evidence bundle offline (discovery evidence needs `make discover`)
	$(RUN) python scripts/generate_evidence.py
