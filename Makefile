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

studio: ## run Glovebox Studio (workspace UI + API) on :8800
	$(RUN) glovebox studio --port 8800

ui: ## rebuild the Studio frontend (needs node 20+); output is committed under src/glovebox/studio/static
	cd ui && npm install --no-audit --no-fund && npx tsc --noEmit && npx vite build

target: ## run the hostile legacy target app on :8089
	$(RUN) glovebox target serve --port 8089

discover: ## real LLM-driven discovery run (needs ANTHROPIC_API_KEY)
	$(RUN) glovebox discover --goal "Look up member 100234 and read their current savings balance" \
		--app-url http://127.0.0.1:8089/ --capability-name member_savings_balance \
		--param member_id=100234 --evidence-dir evidence/discovery
	$(RUN) glovebox validate capabilities/member_savings_balance.json

approve: ## mark the recorded capability as reviewed (gate for unattended replay)
	$(RUN) glovebox catalog approve member_savings_balance $${USER:-reviewer} --notes "reviewed steps, outcomes and risk"

discover-offline: ## same loop with scripted decisions (no key) — for seeing the artifact path
	$(RUN) glovebox discover --goal "Look up member 100234 and read their current savings balance" \
		--app-url http://127.0.0.1:8089/ --capability-name member_savings_balance \
		--param member_id=100234 --offline-script member_savings_balance --console-port 8791

replay: ## deterministic replay of the saved capability
	$(RUN) glovebox replay capabilities/member_savings_balance.json --param member_id=100234 --evidence-dir evidence/replay-success

drift: ## replay the capability under each simulated redesign and report what survived
	$(RUN) glovebox drift member_savings_balance --param member_id=100234

evidence: ## regenerate every replay evidence bundle offline (discovery evidence needs `make discover`)
	$(RUN) python scripts/generate_evidence.py
