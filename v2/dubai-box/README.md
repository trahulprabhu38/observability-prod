# dubai box  (86.106.26.45, Coolify host `dubai`)

Hosts the **`DSP`** Coolify project's prod/global tier (DSP-ADMIN/API/WEB
global + UAE, UAE-DSP-API) and the **Verifiedy (VERIFID)** staging stack.
See `../../Desktop/valura/PARTNER_APPS_AND_UAT_INVENTORY.md` §3 for the full
app list.

Staged here, **not yet deployed** — see the gap below.

| Agent | Port | Status |
|---|---|---|
| cAdvisor | :8085 | **already running** — already has an entry in `prometheus/targets/cadvisor-fleet.yml` (`box: dubai`), but its compose file was never checked into this repo. The `cadvisor/docker-compose.yml` here is a reconstruction matching the standard pattern (`../partner-apps-box/cadvisor/`) — diff it against what's actually running on the box before overwriting anything. |
| node-exporter | :9100 | **missing** — no target in `node-fleet.yml` yet. `node-exporter/docker-compose.yml` here is net-new. |
| Alloy | :12345 / :4317 / :4318 | **missing** — no logs or trace forwarding from this box at all today. `alloy/` here is net-new, modeled on `../partner-apps-box/alloy/` (same Loki/OTel endpoints on `.52`, same level-normalization pipeline). |

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

## Open question

`odd-ostrich-moctoj8muiokpcysqc0c3ynx` (10.200.2.129) holds duplicate
DSP-ADMIN/API/WEB containers inside a Coolify project literally named
`delete-entire-after-confirmation` — per the inventory this is cleanup noise,
**not** something to add monitoring for. Deliberately left out of this
change.
