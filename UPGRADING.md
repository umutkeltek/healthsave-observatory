# Upgrading HealthSave Observatory

How to update an existing install safely. The general procedure:

```bash
git pull
docker compose up -d --build        # the `migrate` service applies additive
                                    # schema migrations before `api` starts
```

Migrations are **always additive** (no table is renamed or dropped), and the
`migrate` service runs them automatically on every boot before the API comes up,
so a plain `up -d --build` is the safe upgrade path.

---

## Version notes

### R1 (2026-06) — release-grade core

Three changes. **Only the first can affect an existing install**, and the default
config carries the common path through transparently.

#### 1. Auth is now default-deny (SECURITY-001) — read this if you run without an API key

Previously, if `API_KEY` was empty the API served your health data **open** (with
a startup warning). Now the PHI surface is **default-deny**: with **no `API_KEY`**
and **no `ALLOW_NO_AUTH`**, those routes return **`503 auth_not_configured`**
instead of serving open.

What this means for you:

| How you run it | Effect on upgrade | Action |
|---|---|---|
| `docker compose up` (this repo's compose) | **None.** The compose now defaults `ALLOW_NO_AUTH=true`, so a keyless local stack keeps serving (with a loud warning). | none |
| You set `API_KEY` (setup.sh / remote-vm deploy / your own) | **None.** Key auth is enforced exactly as before. | none |
| `deploy/remote-vm/deploy.sh` | **None.** It already mints/keeps an `API_KEY`. | none |
| Custom orchestration (raw `docker run`, k8s, systemd) with **no key** | The API returns `503` until configured — this is the intended hardening. | Set `API_KEY=<token>` (recommended for anything network-reachable) **or** `ALLOW_NO_AUTH=true` to deliberately keep it open. |

If you see `503 auth_not_configured`, the startup log tells you exactly what to
set. **Recommendation:** set an `API_KEY` for any install reachable beyond
localhost — this backend stores health data.

#### 2. Optional rate-limiting reverse proxy (SECURITY-004)

New, **opt-in** — nothing changes unless you adopt it. For internet-facing
installs, `deploy/reverse-proxy/` adds an nginx gateway with per-IP rate limiting
and TLS, and closes the direct API port. See its README.

#### 3. Internal refactor (ARCH-001) — no action

Shared parsing/mapping helpers moved below the storage layer
(`normalization.*`, `contracts._base`); `server.ingestion.*` keep working via
re-export shims. No wire, schema, or config change.

---

## iOS app compatibility

The `POST /api/apple/batch` / `GET /api/apple/status` / `GET /api/health` contract
is **frozen and unchanged** — the live App Store HealthSave binary keeps working
across this upgrade. If you set an `API_KEY`, configure the same key in the app.
