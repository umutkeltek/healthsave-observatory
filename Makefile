.PHONY: help regen-lock check-lock test lint format compose-up compose-down

help:
	@echo "Targets:"
	@echo "  regen-lock    Regenerate contracts/openapi/v1.locked.json inside Docker (pinned deps)"
	@echo "  check-lock    Verify contracts/openapi/v1.locked.json matches the live app (no drift)"
	@echo "  test          Run the full pytest suite"
	@echo "  lint          ruff check + ruff format --check"
	@echo "  format        ruff format (writes)"
	@echo "  compose-up    docker compose up -d"
	@echo "  compose-down  docker compose down"

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

test:
	@python3 -m pytest -q

lint:
	@python3 -m ruff format --check .
	@python3 -m ruff check .

format:
	@python3 -m ruff format .
	@python3 -m ruff check --fix .

compose-up:
	@docker compose up -d

compose-down:
	@docker compose down
