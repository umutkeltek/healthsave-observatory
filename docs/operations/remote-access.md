# Remote access without opening ports

At home, the HealthSave app syncs to your Observatory over your own network. Away from home it needs another way in. The safest way opens no port on your router and puts nothing on the public internet: [Tailscale](https://tailscale.com), a private network (a "tailnet") between your own devices.

Observatory includes an optional Tailscale container for this. It stays off until you turn it on.

## What it does

- It joins your tailnet as one device, called `healthsave-observatory` unless you change it.
- It serves the Observatory web app at `https://healthsave-observatory.<tailnet>.ts.net` and the API, which the HealthSave app talks to, at `https://healthsave-observatory.<tailnet>.ts.net:8443`. Both use HTTPS with a certificate that Tailscale issues.
- Only devices signed in to your tailnet can connect. Tailscale Funnel, which would publish a service to the internet, stays off. Nothing else on the server can be reached through it.
- It reaches the web app and the API over the internal Docker network. No new port is published on the host, and `WEB_BIND` can stay `127.0.0.1`.

Your phone and your server talk over an encrypted WireGuard connection. When the two cannot connect directly, Tailscale relays the encrypted traffic, which it cannot read. Turning this on does mean your server contacts Tailscale's coordination service, which learns device names and addresses, never health data. The container runs with `--no-logs-no-support`, so it does not upload its own logs to Tailscale.

## Before you start

1. Create a Tailscale account (the free personal plan is enough), and install the Tailscale app on your phone, signed in to the same tailnet.
2. In the Tailscale admin console, open **DNS** and turn on **MagicDNS** and **HTTPS Certificates**. The container needs both to serve HTTPS.
3. In **Settings -> Keys**, generate an auth key. A one-off key that is not ephemeral is right here.

## Turn it on

Add the key to `.env`:

```bash
TAILSCALE_AUTHKEY=tskey-auth-...
TAILSCALE_HOSTNAME=healthsave-observatory   # optional: the device name on your tailnet
```

Start the container and check that it signed in:

```bash
docker compose --profile tailscale up -d tailscale
docker compose exec tailscale tailscale serve status
```

`serve status` lists the two HTTPS addresses. Your tailnet name (the part before `.ts.net`) is also on the DNS page of the admin console.

The key is used once, at first sign-in. The device's identity is kept in the `tailscale_state` volume, so restarts and `healthsave update` do not need the key again. You can then remove it from `.env` and revoke it in the admin console.

## Pair the app over your tailnet

```bash
healthsave pair --url https://healthsave-observatory.<tailnet>.ts.net:8443
```

Scan the QR code with the HealthSave app. While Tailscale is connected on the phone, the app syncs at home and away with the same address.

## The dashboard stays locked

Anyone on your tailnet can reach the sign-in page, so share your tailnet only with people you trust. The web app still asks for its password (`WEB_PASSWORD`, or Settings -> Web sign-in), and the API still needs the API key.

## Turn it off

```bash
docker compose stop tailscale
docker compose rm -f tailscale
```

Then remove the device in the Tailscale admin console. To forget its identity as well, delete the `tailscale_state` volume (`docker volume ls` shows its full name).

## Troubleshooting

- **The HTTPS addresses do not answer:** HTTPS Certificates is probably off in the tailnet's DNS settings. The first request after it is turned on can take a few seconds while the certificate is issued.
- **The container keeps asking you to sign in:** the auth key expired or was used already. Generate a new one, put it in `.env`, and run `docker compose --profile tailscale up -d tailscale` again.
- **The app cannot reach the server away from home:** check that Tailscale is connected on the phone, and that the app's server address is the `:8443` one.

## Other ways in

- A VPN on your router (WireGuard, OpenVPN) works the same way: connect to it, and pair with the LAN address.
- A reverse proxy with HTTPS on a domain you own: see [Reverse proxy & HTTPS](reverse-proxy.md). It opens a port to the internet, so keep the API key and the web password set.

## See also

- [Security model](security.md) for network exposure and secrets.
- [Deployment](deployment.md) for default ports and bind addresses.
