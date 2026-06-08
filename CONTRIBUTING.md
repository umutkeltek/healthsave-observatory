# Contributing to HealthSave Observatory

Thanks for your interest. This project is **open-core**: the protocol/client layer is open source
(Apache-2.0) and the product core is source-available (Elastic License 2.0). Before contributing,
skim [`LICENSING.md`](./LICENSING.md) so you know which license your change falls under — it's
determined by the path you touch.

## Developer Certificate of Origin (DCO)

We use the **DCO**, not a CLA. It's lightweight: you certify you wrote the patch (or have the right
to submit it) and agree it's contributed under the license of the path it touches. Sign off every
commit:

```
git commit -s -m "your message"
```

This appends a line:

```
Signed-off-by: Your Name <your.email@example.com>
```

By signing off you agree to the DCO (https://developercertificate.org/). Unsigned commits will be
asked to amend with `git commit --amend -s`.

> A **CLA is not required today.** One may be introduced **only if** the core later moves to an
> AGPL-3.0 + commercial dual-license (a CLA is what would let the maintainers offer commercial
> exceptions). If that happens it will be announced clearly and in advance.

## Ground rules that keep the architecture honest

This repo enforces its boundaries with tests — respect them or CI goes red:

- **The v1 ingest contract is frozen.** Never change the shape of `/api/apple/batch`,
  `/api/apple/status`, or `/api/health`, or the OpenAPI lock for them. New client-facing surfaces
  go under `/api/v2/`.
- **DB access lives only in `packages/py/storage/`.** Nothing else imports `sqlalchemy`.
- **Two brains stay separate:** `analysis/statistical/` computes findings (pure, no DB, no HTTP);
  `analysis/llm/` only narrates them.
- **Raw health rows never leave the host.** Cloud egress carries only derived findings/aggregates,
  opt-in.
- Adding a `/api/v2/*` route changes the OpenAPI snapshot — regenerate the lock and confirm the
  diff is v2-only.

See `AGENTS.md` and `CLAUDE.md` for the full boundary rationale and the guard tests that enforce
each rule.

## Workflow

1. Discuss non-trivial changes in an issue first.
2. Test-driven where it applies: a failing test, then the fix, then refactor.
3. `ruff format` + `ruff check` must pass; add/adjust tests; keep `docker compose up -d` working
   with zero config beyond `.env`.
4. Open a PR with signed-off commits and a clear description of what changed and why.

By contributing, you also agree to the [`TRADEMARK.md`](./TRADEMARK.md) policy — contributions do
not grant any right to use the project's marks for your own products.
