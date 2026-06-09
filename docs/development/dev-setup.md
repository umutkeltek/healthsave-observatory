# Development setup

HealthSave Observatory is a Python 3.12 project — FastAPI + TimescaleDB at the core, async SQLAlchemy with asyncpg, `ruff` for lint and format, and `pytest` for tests. Local verification uses the exact same commands as CI, so a green run on your machine is a green run on the pipeline.

Before contributing, skim [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — it covers the DCO sign-off, the architecture boundaries the test suite enforces, and the PR workflow.

## Prerequisites

- **Python 3.12** — the project targets 3.12, matching the Docker image and the CI runtime. Use that version to avoid surprises.
- **Docker** — for the `docker build` step and for running the full stack via Docker Compose.

## Install

Install the package with its dev extras (editable):

```bash
python3.12 -m pip install -e ".[dev]"
```

## Verify locally (same as CI)

Run the same four checks CI runs:

```bash
python3.12 -m ruff format --check .   # formatting
python3.12 -m ruff check .            # lint
python3.12 -m pytest -q               # tests
docker build -t healthsave-observatory-dev . # image builds
```

The test suite runs **without a live database** (async sessions are mocked), so `pytest` works on a clean checkout. Ruff is configured with the `E`, `F`, `I`, `UP`, `B`, and `SIM` rule sets; run `ruff format .` (without `--check`) to auto-fix formatting before committing.

## CI

The GitHub Actions workflow runs formatting, linting, tests, and a Docker build on **every push and pull request to `main`**. Keep all four green locally before opening a PR.

## Architecture boundaries (enforced by tests)

A few rules keep the architecture honest, and CI goes red if you break them — so they matter while you develop, not just at review:

- **The v1 ingest contract is frozen.** Never change the shape of `/api/apple/batch`, `/api/apple/status`, or `/api/health`, or their OpenAPI lock. New client-facing surfaces go under `/api/v2/`. (See the [v1 Apple contract](../api/v1-apple-contract.md).)
- **DB access lives only in `packages/py/storage/`.** Nothing else imports `sqlalchemy`.
- **The two brains stay separate.** The statistical engine computes findings (pure — no DB, no HTTP); the LLM narrator only narrates them.
- **Raw health rows never leave the host.** Cloud egress carries only derived findings/aggregates, opt-in.

Adding a `/api/v2/*` route changes the OpenAPI snapshot — regenerate the lock and confirm the diff is **v2-only** (no v1 drift). Full rationale and the per-rule guard tests are in [`CONTRIBUTING.md`](../../CONTRIBUTING.md) (and the repo's `AGENTS.md` / `CLAUDE.md`).

## Running the stack while you develop

To bring the full stack up locally (TimescaleDB on 5432, FastAPI on 8000, Grafana on 3000):

```bash
cp .env.example .env   # set DB_PASSWORD and GRAFANA_PASSWORD
docker compose up -d
```

`./setup.sh` is the easier path — it generates the passwords for you. For deployment specifics, see [Deployment](../operations/deployment.md).

## Related

- [`CONTRIBUTING.md`](../../CONTRIBUTING.md) — DCO, boundaries, PR workflow
- [Storage backends](storage-backends.md) — the pluggable ingest layer and how to write your own
- [`API_REFERENCE.md`](../../API_REFERENCE.md) — payload-level API reference
