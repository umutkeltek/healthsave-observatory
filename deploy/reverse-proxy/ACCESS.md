# Access card — `apps-vm` (Proxmox-hosted, accessed from your LAN Mac)

`apps-vm` is the LAN-only Proxmox VM that runs `health-data-hub`. **It is
NOT this Mac.** All access is over your LAN at `192.168.33.123` /
`apps-vm` / `apps-vm.lan`.

## URLs (LAN reach, browser on your Mac)

| Surface | URL | Notes |
|---|---|---|
| **Observatory (web dashboard)** | **https://apps-vm.lan:18443/** | Self-signed cert → one-time "Not Secure" → Advanced → Proceed. San list covers `apps-vm.lan`, `apps-vm`, `apps-vm.internal`, `localhost`, `192.168.33.123`, `127.0.0.1`. |
| Same, hostname-only | `https://apps-vm:18443/` | falls under the same cert SAN |
| Same, by IP | `https://192.168.33.123:18443/` | ditto |
| Plain HTTP -> HTTPS redirect | `http://apps-vm.lan:18080/` | 301 -> https |
| API | `https://apps-vm.lan:18443/api/...` | X-API-Key required for PHI endpoints; no-key probes get a `503 auth_not_configured` until you set one |
| **Grafana (PHI dashboards)** | **http://apps-vm.lan:3300/** | Basic-auth (`admin` / `<GRAFANA_PASSWORD>`). Read the live credential with `ssh apps-vm 'sudo grep ^GRAFANA_PASSWORD /srv/localappdata/health-data-hub/.env'`. |

## Hostname quick-reference

`apps-vm.internal` is the VM's own hostname (resolves only on apps-vm).
Your Mac's DNS returns:

```
$ nslookup apps-vm
Address: 192.168.33.123     # ← use THIS on your Mac
$ nslookup apps-vm.internal
NXDOMAIN                  # ← does NOT resolve on your Mac
```

So paste `apps-vm` (or `apps-vm.lan`, or `192.168.33.123`). All three are
covered by the proxy's cert.

## Common issues

- **"Not Secure" in the browser** — expected: the cert is self-signed
  (it's a homelab LAN; no public CA will sign a 192.168.x.x host).
  One-time override on each device. To upgrade to a real CA later,
  swap `/srv/localappdata/health-data-hub/certs/fullchain.pem` +
  `privkey.pem` to a Let's Encrypt pair (DNS-01 challenge works
  without opening inbound 80; or HTTP-01 if your firewall forwards it).
- **Grafana forgot password** — never lose it again; the live value
  lives in `/srv/localappdata/health-data-hub/.env`. To change it,
  edit that file and run `docker compose restart grafana` on
  `apps-vm`. (Default username is `admin` since no
  `GF_SECURITY_ADMIN_USER` override is set.)
