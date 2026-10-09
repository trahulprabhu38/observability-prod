# databases box  (10.200.2.41)

Per the inventory (`PARTNER_APPS_AND_UAT_INVENTORY.md` §6): **nothing shows up
for this box via the Coolify API** — zero apps/databases/services. If
DSP/Monarch/Isolate/NIFM have real production databases, they're either
running directly on this box outside Coolify's management, or external/
managed elsewhere. **That's still an open question — confirm which before
relying on these numbers.** This folder stages the "running directly on the
box" case, since that's the only one Prometheus can reach without more info.

| Agent | Port | Notes |
|---|---|---|
| node-exporter | :9100 | host OS metrics — same pattern as every other box |
| postgres_exporter | :9187 | **placeholder** — needs a real `DATA_SOURCE_NAME` (a read-only Postgres role is enough: `GRANT pg_monitor TO prometheus;` on PG10+). Fill in `postgres-exporter/docker-compose.yml` before deploying. |

No cAdvisor here — this isn't a general Docker/Coolify host, so there's
nothing containerized to enumerate (if that turns out to be wrong, add a
`cadvisor/` folder the same way `../dubai-box/` has one).

## Deploy (once reviewed + DSN filled in)

```bash
scp -r node-exporter postgres-exporter root@10.200.2.41:/root/
# on 10.200.2.41 (root):
cd /root/node-exporter     && docker compose up -d
cd /root/postgres-exporter && docker compose up -d
# open the firewall the same way every other box did:
# ufw allow from 10.200.2.52 to any port 9100 proto tcp
# ufw allow from 10.200.2.52 to any port 9187 proto tcp
```

Then the `databases` entries already staged in
`../prometheus/targets/node-fleet.yml` and `../prometheus/targets/postgres-fleet.yml`
pick it up automatically (`file_sd`, no reload needed).
