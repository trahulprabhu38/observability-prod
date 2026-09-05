# staging box agents  (10.200.2.56 UAE, 10.200.2.57 IND)

Same pattern as `../dev-box/` (10.200.2.51), applied to the two staging
Coolify hosts. Configs here are mirrors — edit here, `scp` up, `docker compose
up -d` on the actual box.

| Box | Region | Coolify project | Agents |
|---|---|---|---|
| `10.200.2.56` (hostname `UAE-staging`) | UAE | `valura-uae-staging` | node-exporter :9100, cAdvisor :8085, Alloy :12345/4317/4318 |
| `10.200.2.57` (hostname `valura-ind-stg`) | IND | `global-valura-staging` | node-exporter :9100, cAdvisor :8085 (per-container metrics via cgroup textfile exporter, see below), Alloy :12345/4317/4318 |

Both boxes already had cAdvisor + a bare-bones `valura-alloy-logs` (logs-only,
no region labels, no trace receiver) before this — that's why `cadvisor-fleet`
already had `.56`/`.57` entries in `prometheus/targets/`. What was added:

- **node-exporter** (new)
- **cAdvisor**: `.56` redeployed to v0.52.1 for consistency (it already worked
  at v0.49 - Docker 28.1.1 there talks to cAdvisor fine). `.57` also bumped to
  v0.52.1 too, though it never surfaced per-container data there either - see `../docs/09-cgroup-metrics-fix.md`.
- **Alloy**: added `coolify_project` / `coolify_resource` / `coolify_env`
  labels, the same `level` normalization pipeline as `../dev-box/`, and an
  OTLP receiver (:4317/:4318) forwarding traces to `10.200.2.52:4317`.
  Redeployed via a proper compose file (previously a bare `docker run`, no
  compose project, no ports published).

## Per-container metrics on `.57`

Fixed via a cgroup-v2 textfile exporter, not cAdvisor - see
`../docs/09-cgroup-metrics-fix.md` for the full story (cAdvisor registers
cleanly but returns zero per-container series on this box; six different
fixes tried, including the one that resolved the identical symptom on `.51`).
`scripts/coolify-cgroup-metrics.sh` runs from cron and feeds node-exporter's
textfile collector instead. Per-container network I/O (RX/TX) is the one
thing this doesn't cover - see that doc for why.

## Firewall

`.56` runs ufw (only 22 + 4000 allowed before this) - added
`ufw allow from 10.200.2.52 to any port 9100 proto tcp` for node-exporter.
`.57` has no firewall (ufw inactive).

## Redeploy

```bash
# on the target box (.56 or .57)
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor      && docker compose up -d
cd /root/alloy         && docker compose up -d
```
