PYTHON ?= uv run --extra dev python
E2E_DB_PASSWORD ?= healthsave-e2e
E2E_GRAFANA_PASSWORD ?= healthsave-e2e
E2E_API_PORT ?= 18000
E2E_DB_HOST_PORT ?= 25434
E2E_COMPOSE_ENV = COMPOSE_FILE=docker-compose.yml DB_PASSWORD=$(E2E_DB_PASSWORD) GRAFANA_PASSWORD=$(E2E_GRAFANA_PASSWORD) API_HOST_PORT=$(E2E_API_PORT) DB_HOST_PORT=$(E2E_DB_HOST_PORT)

.PHONY: help setup install-cli regen-lock check-lock regen-v2-schemas check-v2-schemas regen-ts-client check-ts-client typecheck-ts web-test web-typecheck regen-response-corpus check-response-corpus test e2e lint format verify-local doctor compose-up compose-down

help:
	@echo "Targets:"
	@echo "  setup              One-command install: generate .env + config, then bring the stack up"
	@echo "  regen-lock         Regenerate contracts/openapi/v1.locked.json (Docker, pinned deps)"
	@echo "  check-lock         Verify v1 OpenAPI lock matches the live app (no drift)"
	@echo "  regen-v2-schemas   Regenerate contracts/json-schema/*.json from contracts package (Docker)"
	@echo "  check-v2-schemas   Verify v2 JSON Schemas match the live contract types"
	@echo "  regen-ts-client    Regenerate packages/ts/api-client/src/v[12].ts from the v1 lock + v2 bundle"
	@echo "  check-ts-client    Verify TS client generated files match committed (no drift)"
	@echo "  typecheck-ts       Run tsc --noEmit on the api-client package"
	@echo "  web-test           Run Observatory web Bun tests"
	@echo "  web-typecheck      Run Observatory web TypeScript check"
	@echo "  regen-response-corpus  Regenerate tests/fixtures/apple_healthsave_responses/ (iOS response corpus)"
	@echo "  check-response-corpus  Verify the iOS response corpus matches the live handlers (no drift)"
	@echo "  test               Run the full pytest suite"
	@echo "  e2e                Boot an ephemeral compose stack and run the e2e suite"
	@echo "  lint               ruff check + ruff format --check"
	@echo "  format             ruff format (writes)"
	@echo "  verify-local       Run lint, tests, TS/web checks, and Docker compose E2E"
	@echo "  doctor             Run post-install stack health checks"
	@echo "  install-cli        Install healthsave command wrapper into ~/.local/bin"
	@echo "  compose-up         docker compose up -d"
	@echo "  compose-down       docker compose down"

regen-lock:
	@echo "Building Docker image (pinned FastAPI/Pydantic/Python)..."
	@docker build -t hdh-lockgen . >/dev/null
	@echo "Regenerating contracts/openapi/v1.locked.json (in Docker, pinned env)..."
	@docker run --rm hdh-lockgen python -c \
		"import json; from server.main import app; print(json.dumps(app.openapi(), indent=2, sort_keys=True))" \
		> contracts/openapi/v1.locked.json
	@echo "Done. Diff to review:"
	@git diff --stat contracts/openapi/v1.locked.json || true

check-lock:
	@$(PYTHON) -m scripts.generate_v1_lock --check

regen-v2-schemas:
	@echo "Building Docker image (pinned FastAPI/Pydantic/Python)..."
	@docker build -t hdh-lockgen . >/dev/null
	@echo "Regenerating contracts/json-schema/*.json (in Docker, pinned env)..."
	@mkdir -p contracts/json-schema
	@docker run --rm \
		-v $(PWD)/contracts/json-schema:/out \
		-e SCHEMAS_OUTPUT_DIR=/out \
		hdh-lockgen python -m scripts.generate_v2_schemas
	@echo "Done. Diff to review:"
	@git diff --stat contracts/json-schema/ || true

check-v2-schemas:
	@$(PYTHON) -m scripts.generate_v2_schemas --check

regen-ts-client:
	@cd packages/ts/api-client && bun run generate

check-ts-client:
	@cd packages/ts/api-client && bun run check

typecheck-ts:
	@cd packages/ts/api-client && bun run typecheck

web-test:
	@cd apps/web && bun run test

web-typecheck:
	@cd apps/web && bun run typecheck

regen-response-corpus:
	@$(PYTHON) -m scripts.generate_ios_response_corpus
	@echo "Mirror to the iOS repo and re-run its BackendResponseCorpusTests:"
	@echo "  cp tests/fixtures/apple_healthsave_responses/*.json ../ios_app/Tests/HealthSyncTests/Fixtures/Responses/"

check-response-corpus:
	@$(PYTHON) -m scripts.generate_ios_response_corpus --check

test:
	@$(PYTHON) -m pytest -q

# Black-box end-to-end: boot an isolated compose stack (own project + volume),
# replay the golden iOS batches through it, assert v1 + v2 read surfaces, then
# tear it down. Self-cleaning; preserves the pytest exit code.
e2e:
	@echo "Booting ephemeral e2e stack (project hdh-e2e)..."
	@$(E2E_COMPOSE_ENV) docker compose -p hdh-e2e up -d --build db migrate api
	@echo "Waiting for api readiness..."
	@ready=0; for i in $$(seq 1 60); do \
		if curl -fsS http://localhost:$(E2E_API_PORT)/ready >/dev/null 2>&1; then ready=1; break; fi; \
		sleep 2; \
	done; \
	if [ "$$ready" != "1" ]; then \
		echo "API did not become ready; recent logs:"; \
		$(E2E_COMPOSE_ENV) docker compose -p hdh-e2e logs --tail=80 api; \
		$(E2E_COMPOSE_ENV) docker compose -p hdh-e2e down -v >/dev/null 2>&1; \
		exit 1; \
	fi
	@E2E_BASE_URL=http://localhost:$(E2E_API_PORT) $(PYTHON) -m pytest -m e2e -q tests/e2e; rc=$$?; \
		$(E2E_COMPOSE_ENV) docker compose -p hdh-e2e down -v >/dev/null 2>&1; exit $$rc

lint:
	@$(PYTHON) -m ruff format --check .
	@$(PYTHON) -m ruff check .

format:
	@$(PYTHON) -m ruff format .
	@$(PYTHON) -m ruff check --fix .

verify-local: lint test check-ts-client typecheck-ts web-test web-typecheck e2e

doctor:
	@./healthsave doctor

setup:
	@./healthsave setup

install-cli:
	@./healthsave install-cli

compose-up:
	@docker compose up -d

compose-down:
	@docker compose down
