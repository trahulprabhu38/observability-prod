# dubai box  (86.106.26.45, Coolify host `dubai`)

Hosts the **`DSP`** Coolify project's prod/global tier (DSP-ADMIN/API/WEB
global + UAE, UAE-DSP-API) and the **Verifiedy (VERIFID)** staging stack.
See `../../Desktop/valura/PARTNER_APPS_AND_UAT_INVENTORY.md` §3 for the full
app list.

Staged here, **not yet deployed** — see the gap below.

## Reachability (checked 2026-10-09, from the observability box over VPN)

**The box is alive and actively serving production traffic** — this is a
firewall gap, not an outage:

| Check | Result |
|---|---|
| `ping 86.106.26.45` | **responds**, ~260ms RTT (consistent with an actually-remote Dubai location) |
| `:443` (its apps, e.g. `dsp.valura.ai`) | **open** — real users are hitting it right now |
| `:22` (SSH) | **closed/filtered** |
| `:8085` (cAdvisor) | **closed/filtered** — confirmed from Prometheus itself: `context deadline exceeded` |
| `:9100` (node-exporter) | **closed/filtered**, same |

**Action needed from whoever controls this box's firewall:** open 22 (so
this repo's agents can be deployed) and 8085/9100 (so Prometheus on `.52`
can scrape them) to `10.200.2.52` at minimum, same as the `ufw allow from
10.200.2.52` rule every other box already has. Nothing in this repo can fix
that from the outside.

| Agent | Port | Status |
|---|---|---|
| cAdvisor | :8085 | **target exists in `cadvisor-fleet.yml` but is down** — either something was deployed once and the port got firewalled after, or the target was added speculatively and nothing's actually listening. Can't tell which until :8085 is reachable. The `cadvisor/docker-compose.yml` here is a reconstruction matching the standard pattern (`../partner-apps-box/cadvisor/`) — diff it against what's actually running before overwriting anything, once you can reach the box. |
| node-exporter | :9100 | **missing** — no target in `node-fleet.yml` yet. `node-exporter/docker-compose.yml` here is net-new. |
| Alloy | :12345 / :4317 / :4318 | **missing** — no logs or trace forwarding from this box at all today. `alloy/` here is net-new, modeled on `../partner-apps-box/alloy/` (same Loki/OTel endpoints on `.52`, same level-normalization pipeline). |

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

All of these already show up correctly in the Partner Apps dashboard's
"Service status - Coolify API" panel (it reads Coolify's own API, not
cAdvisor, so it doesn't depend on this box being reachable). They will
**not** get CPU/memory/log panels until the firewall gap above is fixed.

## Deploy (once reviewed)

```bash
# from this machine
scp -r node-exporter alloy cadvisor root@86.106.26.45:/root/

# on 86.106.26.45 (root)
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor      && docker compose up -d   # confirm first whether this would duplicate what's already running
cd /root/alloy         && docker compose up -d

# check/open the firewall for node-exporter the same way partner-apps-box did:
# ufw allow from 10.200.2.52 to any port 9100 proto tcp
```

Then uncomment/add the node-exporter line in
`../prometheus/targets/node-fleet.yml` (already done in this change — see
the `dubai` entry) and `make reload-prometheus` isn't even needed, it's
`file_sd` — just check **Status → Targets** in Prometheus after the agent is
up.

## The "dsp-admin-prod-global" you'll see in cAdvisor on valura-prod is NOT this box's real app

`odd-ostrich-moctoj8muiokpcysqc0c3ynx` (`destination.server` IP
10.200.2.129) holds duplicate `DSP-ADMIN-prod-GLOBAL` / `DSP-API-prod-global`
/ `DSP-WEB-prod-GLOBAL` containers inside a Coolify project literally named
`delete-entire-after-confirmation` — per the inventory this is cleanup noise.
Their preview FQDNs (e.g. `*.10.200.2.54.sslip.io`) actually point at
**valura-prod** (10.200.2.54), not .129, which is why cAdvisor *there*
reports one container as `coolify_resourceName=dsp-admin-prod-global` under
project slug `dsp-new-server` — that's this stale duplicate, not the real
`DSP-ADMIN-prod-GLOBAL` on this box. It was mistakenly treated as real data
in an earlier pass of the Partner Apps dashboard and has been removed from
there. Left out of monitoring here deliberately, matching the inventory's
original recommendation.
