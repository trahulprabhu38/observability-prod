# dubai box  (86.106.26.45, Coolify host `dubai`)

Hosts the **`DSP`** Coolify project's prod/global tier (DSP-ADMIN/API/WEB
global + UAE, UAE-DSP-API) and the **Verifiedy (VERIFID)** staging stack.
See `../../Desktop/valura/PARTNER_APPS_AND_UAT_INVENTORY.md` §3 for the full
app list.

## Status (as of 2026-10-09): metrics live, logs live, traces still blocked

| Agent | Port | Status |
|---|---|---|
| node-exporter | :9100 | **deployed, scraping successfully** (`up` in Prometheus) |
| cAdvisor | :8085 | **deployed, scraping successfully** — 17 real containers visible, including all 9 DSP/VERIFID apps below |
| Alloy (logs) | :12345 | **deployed, pushing successfully** — see "the push path" below for how |
| Alloy (traces) | :4317 / :4318 | **still broken** — same root cause as logs were (no route to `10.200.2.52`), but traces haven't been routed through `loki-infra`-style public ingress yet. Open item. |

SSH here goes through **port 2953, not 22** (confirmed live: 22 is actively
refused, 2953 is open) — this box hardens SSH onto a non-standard port, it
isn't firewalled off. Deploy/redeploy via:

```bash
scp -P 2953 -r node-exporter cadvisor alloy root@86.106.26.45:/root/
ssh -p 2953 root@86.106.26.45
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor      && docker compose up -d
cd /root/alloy         && docker compose up -d   # needs ./alloy/.env - see below
```

ufw also needed three rules opened, scoped to the **observability box's
public egress IP (`103.183.157.251`), not its private IP (`10.200.2.52`)**
— dubai is a standalone public server, not on the same private VPN mesh as
every other box, so `.52`'s outbound traffic arrives here NAT'd to that
public IP:

```bash
ufw allow from 103.183.157.251 to any port 22   proto tcp
ufw allow from 103.183.157.251 to any port 8085 proto tcp
ufw allow from 103.183.157.251 to any port 9100 proto tcp
```

## The push path for logs: why it needed a public endpoint + auth

Metrics work because Prometheus on `.52` *pulls* from dubai's public IP —
no networking problem there. Logs are different: Alloy *pushes* to Loki, and
`10.200.2.52` is a private IP dubai has no route to at all (confirmed: 100%
ping loss). So `config.alloy` here points at
`https://loki-infra.valura.co.in/loki/api/v1/push` instead — a Traefik
route on the Coolify host (`10.200.1.2`, see
`/data/coolify/proxy/dynamic/observability.yml`) that already existed and
already forwarded to `.52:3100`, just with **zero authentication** (found
live and open to the entire internet while fixing this — unrelated to
dubai, worth knowing regardless). Added a Traefik `basicAuth` middleware
scoped to just that one router.

Alloy authenticates with `basic_auth { username = "dubai-alloy", password =
sys.env("LOKI_PUSH_PASSWORD") }` — the password is **not** in this repo.
Before `docker compose up -d` in `alloy/`, create `alloy/.env` on the box
itself (gitignored, never committed, same pattern as the main stack's
`v2/.env`):

```bash
echo 'LOKI_PUSH_PASSWORD=<the password>' > /root/alloy/.env
```

(Ask whoever ran the Traefik change for the password — it's the one behind
the bcrypt hash in `observability.yml`, not written down here on purpose.)

Traces still go to the old unreachable `10.200.2.52:4317` in `config.alloy`
— left as a known-broken no-op rather than silently dropped, since fixing
it needs the same kind of public-ingress treatment Loki just got (not done
yet, OTel isn't HTTP-basic-auth-friendly the same simple way).

## What's actually hosted here (verified live via the Coolify API, 2026-10-09)

Real app names and their Coolify `uuid` (not the inventory doc's possibly-stale
names), all project `DSP`:

- `DSP-ADMIN-prod-GLOBAL` (`mexhmli7tjancs6tqaxmzsxs`) — https://dspadmin.valura.ai
- `DSP-API-prod-global` (`jrcikijh63ng07z1ivx3hskr`) — https://dsp-api.valura.ai, `running:healthy`
- `DSP-WEB-prod-GLOBAL` (`r51jjkkmpcbjugjqo7cevpn1`) — https://dsp.valura.ai
- `DSP-WEB-prod-UAE` (`r6uf0zy23awnciy7volwz3q6`) — dsp.valura.ae / dsp.valura.ai
- `UAE-DSP-API` (`ywbz70dxwf5r5qky1nem9qds`) — dsp-api.valura.ae / dsp-api.valura.ai
- `VERIFID-ADMIN-stg` (`kzgna6nsf6an6ki8nfo0up75`) — https://verifid-admin.valura.co.in, `running:healthy`
- `VERIFID-API-stg` (`lndb04bwmeifbaf6q9ikwxoc`) — https://verifidapi.valura.co.in, `running:healthy`
- `VERIFID-BACKEND-stg` (`j5alkk0xrw29uvn37if184bg`) — https://backend.valura.co.in, `running:healthy`
- `VERIFID-WEB-stg` (`zrgoz3i8hfwjfzl9lotekkyn`) — https://verifid.valura.co.in, `running:healthy`
- `depricated-verif-id-api` / `depricated-verif-id-web` — `exited:unhealthy`, legacy, presumably safe to ignore

All of these show up in the Partner Apps dashboard's "Service status -
Coolify API" panel (reads Coolify's own API directly) **and** now have real
CPU/memory data in the "Service status - cAdvisor" panel + the `$resource`
dropdown, under these cAdvisor resource names: `dsp-admin-prod-global`,
`dsp-api` (= UAE-DSP-API), `dsp-api-prod-global`, `dsp-web` (=
DSP-WEB-prod-UAE), `dsp-web-prod-global`, `verifid-admin-stg`,
`verifid-api-stg`, `verifid-backend-stg`, `verifid-web-stg`.

## The "dsp-admin-prod-global" you'll see in cAdvisor on valura-prod is NOT this box's real app

`odd-ostrich-moctoj8muiokpcysqc0c3ynx` (`destination.server` IP
10.200.2.129) holds duplicate `DSP-ADMIN-prod-GLOBAL` / `DSP-API-prod-global`
/ `DSP-WEB-prod-GLOBAL` containers inside a Coolify project literally named
`delete-entire-after-confirmation` — per the inventory this is cleanup noise.
Their preview FQDNs (e.g. `*.10.200.2.54.sslip.io`) actually point at
**valura-prod** (10.200.2.54), not .129, which is why cAdvisor *there*
reports one container as `coolify_resourceName=dsp-admin-prod-global` under
project slug `dsp-new-server` — same resource name as the real one on this
box now that cAdvisor is deployed here too, which would silently sum the
stale container's numbers into the real one's. Every cAdvisor query in the
Partner Apps dashboard explicitly adds `box!="valura-prod"` to exclude it
(see `apps.json`'s description for the full note). Left out of monitoring
on `valura-prod` itself, matching the inventory's original recommendation.
