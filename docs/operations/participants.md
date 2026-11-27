# Participants (one Observatory for a coach or clinic)

One HealthSave Observatory can hold several people. A coach installs it once for a team, a clinic once
for a group, and every athlete or participant gets their own key. The phone that holds a key writes
that person's data and nobody else's. The HealthSave app needs nothing new: the participant pairs it
exactly as you pair your own phone.

Each person's data stays on the machine that runs the Observatory. Only a SHA-256 of each key is
stored; the key itself is printed once.

## Before you start

- The Observatory runs (`healthsave setup basic`, then `healthsave up`) and has an API key. The key in
  `.env` stays yours: it is the admin key the web dashboard and your own phone use.
- Participants' phones can reach the server. On one network the LAN address works. From anywhere
  else, put HTTPS in front of it first ([Reverse proxy & HTTPS](reverse-proxy.md)).

## Add a participant

```bash
healthsave participants add "Alice Smith" --url https://observatory.example.com
```

This prints the server URL, a new key and the same pairing QR that `healthsave pair` prints (the QR
needs `qrencode`; without it, type the two values in). Give it to that person only. On their iPhone:
HealthSave → Settings → Server Sync, then scan the QR or enter the URL and key. From the first sync on,
their data lands under their own name.

Run it once per person. A name can hold one live phone key at a time.

## See each person's data

When the Observatory holds more than one person, the web sidebar shows **Viewing** with a list of
people. Pick one and every page re-reads for that person:

| Follows the person you pick | Stays with the primary person (you) |
|---|---|
| Today, Sleep and Activity charts, Data, Explore, Compare, Library | Findings, Relationships and the weekly Body Brief |
| Sources, devices and streams | Experiments |
| Data readiness and "synced" status | Moments (life events) and Timeline |
| Export | Receipts, analytical time settings |

The pages in the right-hand column show nothing while a participant is selected, and they refuse
changes, so a participant's charts never sit next to your own findings. The choice resets when the
browser closes. Privacy and Intelligence settings belong to the machine, not to a person, and look
the same for everyone.

## List, revoke, re-pair

```bash
healthsave participants list
healthsave participants revoke "Alice Smith"
```

`list` shows each person, whether their key is live, and when their data last arrived. `revoke`
stops that key at once (the phone gets `401` and stops syncing). Their data stays and stays visible
to you. If a phone is lost, revoke the name and add it again: the new key writes into the same
person's history.

## Read-only keys

```bash
healthsave participants add "Alice Smith" --read
```

A read key lets that person's own tools (a script, an MCP client) read their own data through the
[v2 read API](../api/v2-read-api.md): the owner-scoped reads and their own sync status, nothing else.

To connect your own AI client to your own record, use `healthsave mcp` instead: it makes a
read key for you, the primary person ([Give your AI a body](../mcp.md)).

## What a participant key can do

| Key | Can call | Whose data |
|---|---|---|
| `ingest` (default, the phone) | `POST /api/apple/batch`, `POST /api/v2/apple/batch`, `GET /api/apple/status`, `GET /api/apple/coverage`, `/api/v2/sync/runs/*` | its own person, always |
| `read` (`--read`) | GETs on the above, plus series, export, sources, devices, streams and readiness | its own person, always |
| `read` for you (`healthsave mcp key`) | the same reads, plus findings, lab results and the time setting | the primary person only |
| the `.env` key (admin) | everything | the primary person; any person with `?owner=` |

Anything else answers `403`. A revoked key answers `401`. The admin lists people with
`GET /api/v2/owners`; see the [API reference](../../API_REFERENCE.md).

## Limits today

- Participants do not sign in to the dashboard. You see their data; they see their own phone.
- Findings, Body Briefs and experiments are computed for the primary person only.
- A participant view groups days by the default calendar (UTC midnight); the analytical-time
  setting in Settings is the primary person's.
- The Home Assistant / MQTT bridge publishes one person: the primary person (the owner your `.env`
  admin key maps to), or the one named in `HEALTHSAVE_BRIDGE_OWNER`. It never publishes a
  participant's rows to your Home Assistant ([Home Assistant and MQTT](../integrations/home-assistant.md)).
- The bundled Grafana dashboards read every row on the machine, across people. On an Observatory
  that holds participants, filter the panels by `owner_id` yourself
  ([Multi-user / household](multi-user.md)).

## See also

- [Security model](security.md) - API keys, network exposure, secret storage
- [Backups & migrations](backup-and-migrations.md) - migration `029_api_keys.sql` adds the key table
