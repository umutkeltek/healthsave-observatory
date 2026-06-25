# Development Setup

HealthSave Observatory is a Python 3.12 project with FastAPI, TimescaleDB, async SQLAlchemy/asyncpg, `ruff`, `pytest`, a generated TypeScript client, and the Observatory web app. Local verification uses the same commands CI uses.

Before contributing, skim [`CONTRIBUTING.md`](../../CONTRIBUTING.md). It covers DCO sign-off, architecture boundaries, the test suite, and PR workflow.

## Prerequisites

- **Python 3.12** - matches the Docker image and CI runtime.
- **uv** - local Python dependency runner used by the Makefile.
- **Docker** - required for image build, compose stack, and E2E.
- **bun** - required for the TypeScript client and Observatory web checks.

macOS and Linux run natively. On Windows, use WSL2 with Docker Desktop WSL integration enabled.

## Install

```bash
uv sync --extra dev
```

## Verify Locally

Preferred full local verification:

```bash
./healthsave verify
```

Faster inner-loop checks:

```bash
make lint
make test
make web-test
make web-typecheck
make e2e
```

Lower-level CI-equivalent commands:

```bash
uv run --extra dev python -m ruff format --check .
uv run --extra dev python -m ruff check .
uv run --extra dev python -m pytest -q
docker build -t healthsave-observatory-dev .
```

The unit test suite runs without a live database; async sessions are mocked, so `make test` works on a clean checkout. Run `make format` to apply ruff formatting and safe fixes before committing.

## Running The Stack

Use the CLI for the full local stack:

```bash
./healthsave setup basic
./healthsave doctor
./healthsave status
```

Default layers are TimescaleDB, migrations, API, worker, Observatory web, and Grafana. See the complete layer map:

```bash
./healthsave layers
```

Manual compose still works if you need it:

```bash
cp .env.example .env
# Set DB_PASSWORD and GRAFANA_PASSWORD.
cp config.yaml.example config.yaml
docker compose up -d
```

For deployment specifics, see [Deployment](../operations/deployment.md).

## CI

GitHub Actions runs formatting, linting, tests, Docker build, TypeScript checks, web checks, and E2E on pushes and pull requests. Keep `./healthsave verify` green before opening a PR.

## Architecture Boundaries

These rules keep the architecture honest and are enforced by tests:

- **The v1 ingest contract is frozen.** Do not change `/api/apple/batch`, `/api/apple/status`, `/api/health`, or the v1 OpenAPI lock. New client-facing surfaces go under `/api/v2/`.
- **DB access lives only in `packages/py/storage/`.** Nothing else imports `sqlalchemy`.
- **The two brains stay separate.** The statistical engine computes findings; the LLM narrator only narrates them.
- **Raw health rows never leave host.** Cloud egress carries only derived findings or aggregates, and only when explicitly enabled.

Adding a `/api/v2/*` route changes OpenAPI snapshots. Regenerate the lock and confirm the diff is v2-only. Full rationale lives in [`CONTRIBUTING.md`](../../CONTRIBUTING.md), repo `AGENTS.md`, and `CLAUDE.md`.

## Related

- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) - DCO, boundaries, PR workflow
- [Storage backends](storage-backends.md) - pluggable ingest layer
- [`API_REFERENCE.md`](../../API_REFERENCE.md) - payload-level API reference
