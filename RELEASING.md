# Releasing HealthSave Observatory

Self-hosters install tags, not `main`. A fix that someone needs on their server
reaches them only once it ships in a tagged release, so every such fix gets one.

## Versions

Tags are `vX.Y.Z` ([semantic versioning](https://semver.org)). The version is
stated in `pyproject.toml` and in the FastAPI app (`apps/api/server/main.py`),
and the OpenAPI lock snapshots it. `tests/contract/test_release_version_coherence.py`
fails CI when they disagree.

- **Patch** (`1.1.0` → `1.1.1`): fixes and docs only. No new route, field,
  migration or setting.
- **Minor** (`1.1.0` → `1.2.0`): additive surface. A new `/api/v2/*` route or
  field, a new migration (migrations are additive by rule), or a new optional
  setting.
- **Major**: a change that breaks a shipped client or an existing install. The
  routes the App Store app depends on (`POST /api/apple/batch`,
  `GET /api/apple/status`, `GET /api/health`) never change, so a major release
  should not happen. If one seems necessary, redesign the change instead.

Plugins carry their own versions, independent of the server.

## When to release

- When a customer is told about a server fix, the fix must already be in a
  release. Link the release in the reply, not a commit.
- Deploy a release by its tag (`DEPLOY_REF=vX.Y.Z` for
  `deploy/remote-vm/deploy.sh`). That way the running server matches a
  published release, and `current-release.env` records which one.

## Cutting a release

1. Bump the version in `pyproject.toml` and `apps/api/server/main.py`, then run
   `make regen-lock` (Docker, pinned environment). The lock diff should be the
   `info.version` line plus any surface change you meant to make.
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section to the top of `CHANGELOG.md`. Write
   it for the person running the server: how to upgrade, what was fixed, what
   was added, and what stays compatible.
3. Commit, push `main`, and wait for CI to pass.
4. Run `make release VERSION=X.Y.Z DRY_RUN=1`, then `make release VERSION=X.Y.Z`.
   `scripts/release.sh` refuses to tag unless `main` is clean and pushed, CI
   passed on that exact commit, the version and changelog agree
   (`scripts/release_notes.py`), and the tag is unused. It then pushes an
   annotated tag.
5. The tag push runs `.github/workflows/release.yml`. It checks the version
   again, publishes the `ghcr.io/umutkeltek/healthsave-observatory:vX.Y.Z`
   image, and creates the GitHub Release from the changelog section. Confirm
   both exist before you announce the release.

## Never

- Never move or delete a published tag. Fix forward with a new patch release.
- Never tag a commit whose CI has not passed.
- Never rewrite a release's notes to change what it shipped. Add a correction
  instead.
