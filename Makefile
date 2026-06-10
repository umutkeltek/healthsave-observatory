.PHONY: help setup regen-lock check-lock regen-v2-schemas check-v2-schemas regen-ts-client check-ts-client typecheck-ts regen-response-corpus check-response-corpus test e2e lint format doctor compose-up compose-down

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
	@echo "  regen-response-corpus  Regenerate tests/fixtures/apple_healthsave_responses/ (iOS response corpus)"
	@echo "  check-response-corpus  Verify the iOS response corpus matches the live handlers (no drift)"
	@echo "  test               Run the full pytest suite"
	@echo "  e2e                Boot an ephemeral compose stack and run the e2e suite"
	@echo "  lint               ruff check + ruff format --check"
	@echo "  format             ruff format (writes)"
	@echo "  doctor             Run post-install stack health checks"
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
	@python3 -m scripts.generate_v1_lock --check

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
	@python3 -m scripts.generate_v2_schemas --check

regen-ts-client:
	@cd packages/ts/api-client && bun run generate

check-ts-client:
	@cd packages/ts/api-client && bun run check

typecheck-ts:
	@cd packages/ts/api-client && bun run typecheck

regen-response-corpus:
	@python3 -m scripts.generate_ios_response_corpus
	@echo "Mirror to the iOS repo and re-run its BackendResponseCorpusTests:"
	@echo "  cp tests/fixtures/apple_healthsave_responses/*.json ../ios_app/Tests/HealthSyncTests/Fixtures/Responses/"

check-response-corpus:
	@python3 -m scripts.generate_ios_response_corpus --check

test:
	@python3 -m pytest -q

# Black-box end-to-end: boot an isolated compose stack (own project + volume),
# replay the golden iOS batches through it, assert v1 + v2 read surfaces, then
# tear it down. Self-cleaning; preserves the pytest exit code.
e2e:
	@echo "Booting ephemeral e2e stack (project hdh-e2e)..."
	@docker compose -p hdh-e2e up -d --build db migrate api
	@echo "Waiting for api readiness..."
	@for i in $$(seq 1 60); do curl -fsS http://localhost:8000/ready >/dev/null 2>&1 && break || sleep 2; done
	@E2E_BASE_URL=http://localhost:8000 python3 -m pytest -m e2e -q tests/e2e; rc=$$?; \
		docker compose -p hdh-e2e down -v >/dev/null 2>&1; exit $$rc

lint:
	@python3 -m ruff format --check .
	@python3 -m ruff check .

format:
	@python3 -m ruff format .
	@python3 -m ruff check --fix .

doctor:
	@./setup.sh doctor

setup:
	@./setup.sh

compose-up:
	@docker compose up -d

compose-down:
	@docker compose down
