# Give your AI a body (MCP)

Your Observatory can answer your own AI client. Ask Claude "how did I sleep this
year?" and it reads the answer from your own server: nights, hours asleep, bedtimes,
the nights with no data, month by month. It works with Claude Code, Claude Desktop
and any other client that speaks [MCP](https://modelcontextprotocol.io).

The server is read-only. It talks to your Observatory and nothing else.

## What it can answer

| Ask | Tool your AI calls |
|---|---|
| "How did I sleep this year?" "Was last night normal for me?" | `sleep_summary` |
| "How active was I last month?" "What was my best day?" | `activity_summary` |
| "How am I today compared with usual?" | `today_vs_usual` |
| "Show my resting heart rate since spring." | `metric_trend` |
| "What has changed lately?" | `findings` |
| "What do my iron results say?" | `lab_results` |
| "What did my year look like? When did I start wearing the ring?" | `year_in_health` |
| "What data do you have about me?" | `observatory_overview` |

Every answer carries its units, where it came from (`read_from`) and its limits
(`limitations`, below). Each reading is compared with your own history, not with a
population. Nothing is a diagnosis.

## Set it up (one line)

On the computer that runs your Observatory:

```bash
healthsave mcp
```

It makes a read-only key the first time, then prints one setup line per AI client
with this server's address and that key filled in. Paste the line on the computer
where your AI runs. For Claude Code it looks like this:

```bash
claude mcp add healthsave -e HEALTHSAVE_URL=http://192.168.1.20:8000 -e HEALTHSAVE_API_KEY=<your read key> -- uvx --from "git+https://github.com/umutkeltek/healthsave-observatory@v1.4.0#subdirectory=packages/mcp" healthsave-mcp
```

Then ask Claude about your sleep. `claude mcp list` shows `healthsave` as connected.

| Client | How |
|---|---|
| Claude Code | The `claude mcp add` line above. Needs [uv](https://docs.astral.sh/uv/). |
| Claude Desktop | `healthsave mcp --client claude-desktop` prints a block for Settings > Developer > Edit Config (`mcpServers`). Restart Claude. Needs uv. |
| No uv, but Docker | `healthsave mcp --client docker` prints the same line with `docker run ... ghcr.io/umutkeltek/healthsave-observatory:<version> /opt/healthsave-mcp/bin/healthsave-mcp`. It is the image your stack already runs. |
| Other MCP clients | Run `healthsave-mcp` (stdio) with `HEALTHSAVE_URL` and `HEALTHSAVE_API_KEY` set. |
| ChatGPT | Not yet. ChatGPT reaches MCP servers from OpenAI's cloud over HTTPS, so it would need your Observatory open to the internet. This release runs on your own computers only. |

The setup line pins the MCP server to the release your stack runs, so the two never
drift apart. After `healthsave update`, run `healthsave mcp` again and paste the new line.

Check that everything works, end to end, on the server:

```bash
healthsave mcp --check
```

It starts the MCP server inside your API container the way an AI client would, calls
one tool, and prints what the key may read.

## The key

`healthsave mcp` makes a **read key for you**, the primary person. It can read your
readings, findings, lab results and time setting. It cannot change anything: every
route that writes answers `403` to a read key, and a test fails the build if one
ever does not. The key is kept in `.env` as `MCP_READ_KEY`; only its SHA-256 is in the
database.

The key itself can read your raw readings through the API (that is what a read key
is). The MCP tools pass only summaries to the AI, but the key sits in your AI client's
config file, so treat it like a password and rotate it if that file leaves your hands.

```bash
healthsave mcp key            # show it
healthsave mcp key --rotate   # replace it; the old key stops at once
```

Do not give your AI client the admin key from `.env` (`API_KEY`); it can change
settings.

A participant (coach or clinic setups, [Participants](operations/participants.md)) can
use their own read key, `healthsave participants add "Alice" --read`. It reads that
person's sleep, activity, readings and year. Findings and lab results are computed for
the primary person, so for a participant's key the tools say `key_scope` instead.

## What it never does

- **It never writes.** All eight tools are marked read-only to the client, the
  server sends only `GET` requests, and the key cannot write.
- **It never hands your AI raw readings.** The MCP server runs on the AI's computer,
  reads from your Observatory (up to 5,000 readings per request, over your own
  network) and turns them into summaries: one value per day or per night, monthly
  rows for long periods, findings the statistical engine already computed. Lab results
  are the exception: they are listed one by one, at most 20 per marker. Away from
  home, reach your server over HTTPS or Tailscale ([Remote access](operations/remote-access.md)),
  never plain HTTP across the internet.
- **It never talks to anyone else.** The server connects to `HEALTHSAVE_URL` only. It
  does not follow redirects and ignores proxy settings.
- **It never diagnoses.** It tells your AI to describe, not to give medical advice.

What does leave: **the answers your AI reads go to that AI's provider.** If you use
Claude, the summaries it reads are sent to Anthropic like the rest of your
conversation. Your record itself stays on your hardware. For nothing to leave at
all, use an MCP client that runs a local model.

The Observatory does not log which tool your AI called. Your AI client's own history
shows every call and its answer.

## Periods and limits

Sleep: `last_night`, `last_7_nights`, `last_30_nights`, `last_90_nights`,
`last_365_nights`, `this_year`. Activity and `metric_trend`: `today`, `last_7_days`,
`last_30_days`, `last_90_days`, `last_365_days`, `this_year`. Up to 14 nights or days are
listed one by one; longer periods add one row per month.

| Limitation code | Meaning |
|---|---|
| `window_cut` | The Observatory returns at most 5,000 readings per request and keeps the newest. The answer says from which day it is complete. Ask for a shorter period for full detail. |
| `time_basis_utc` | The key cannot read your time zone setting, so days are grouped in UTC. |
| `key_scope` | This key may not read that part of the record (a participant's key and findings, for example). |
| `today_in_progress` | Today's totals are still counting and are kept out of the averages. |
| `one_source_of_several` | No all-source day total, so one device's totals are used and the others left out, never added. |
| `sources_disagree` | Two sources reported different sleep stages at the same time. |
| `record_starts_late` | The period starts before your first data. |
| `no_data`, `no_findings` | Nothing recorded, or no findings computed yet. |
| `list_cut` | A long list was shortened; the detail says how. |
| Year codes (`partial_year`, `device_labels`, ...) | Passed through from [Year in Health](api/v2-read-api.md). |

Two sources are never averaged: when a ring and a watch both measure resting heart
rate, `today_vs_usual` and `metric_trend` use one and name the other.

## Troubleshooting

| You see | Do |
|---|---|
| `unreachable: Could not reach the Observatory` | The AI's computer cannot reach `HEALTHSAVE_URL`. Same network? Away from home, see [Remote access](operations/remote-access.md). |
| `key_rejected` (401) | The key was rotated or the database restored. On the server: `healthsave mcp key --rotate`, then `healthsave mcp`, and paste the new line. |
| `key_scope` on findings | You use a participant's key. On the server, `healthsave mcp` makes the primary person's key. |
| `--check` says the image has no MCP server | Update the stack: `healthsave update` (1.4.0 or newer). |
| `uvx: command not found` | Install uv, or use the Docker line. |
| `Unknown command: mcp` | Your `healthsave` comes from an older npm package. Run `./healthsave mcp` inside the Observatory folder (default `~/healthsave-observatory`). |

Licensed under Elastic License 2.0. Source: [`packages/mcp`](../packages/mcp).
