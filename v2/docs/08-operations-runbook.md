# 08 - Operations runbook

Day-2 stuff: reloads, health checks, upgrades, backups, capacity, incidents.

## Start / stop / status

```bash
make up            # docker compose up -d
make ps            # status of every container
make down          # stop, keep data
make nuke          # stop AND delete all volumes (irreversible)
make logs S=loki   # tail one service
make ecs-up        # up + the ECS/CloudWatch exporter profile
```

## Config changes - what needs what

| You edited | Apply with | Restart? |
|---|---|---|
| `prometheus/prometheus.yml`, `prometheus/rules/*` | `make validate && make reload-prometheus` | no |
| `prometheus/targets/*.yml` | nothing - `file_sd` re-reads every 30s | no |
| `alloy/config.alloy` | `make reload-alloy` | no |
| `loki/loki.yml` | `docker compose restart loki` | yes |
| `otel-collector/config.yaml` | `make validate && docker compose restart otel-collector` | yes |
| `alertmanager/alertmanager.yml` | `docker kill -s HUP alertmanager` (or `restart`) | no (HUP) |
| `grafana/provisioning/*` | `docker compose restart grafana` | yes |
| `docker-compose.yml` (image tags, ports, flags) | `make up` (recreates changed) | changed only |

Always `make validate` before reloading Prometheus / Alertmanager / the
collector - a broken config on reload keeps the **old** config running for
Prometheus, but a broken collector/loki config **fails to start**.

**Gotcha - editing a config with `sed -i` (or vim, or anything that writes via
a temp file + rename) can silently break a single-file Docker bind mount.**
Docker binds the *inode* the file had at container start; a rename-based edit
swaps in a new inode at that path, so the container keeps serving the *old*
content forever, no matter how many times you `reload`/`HUP`/curl `/-/reload`
- there's nothing to detect because the mount isn't broken, it's just stale.
Symptom: you edit `prometheus.yml`, reload, and the change never takes
effect; `docker exec <container> cat <path>` still shows the old content.
Fix: `docker compose restart <service>` - that remounts against the current
inode. Prefer in-place edits (`>>` append, or a tool that truncates+rewrites
rather than rename) when you can, so a live reload actually picks them up.

## Health check tour (run when something feels off)

```bash
make prom-targets                              # every scrape target + health
curl -s localhost:9090/-/healthy               # Prometheus
curl -s localhost:9093/-/healthy               # Alertmanager
curl -s localhost:3100/ready                   # Loki
curl -s localhost:13133/                       # OTel Collector health_check
curl -s localhost:16686/                       # Jaeger UI up
curl -s localhost:12345/-/ready                # Alloy
curl -s 'localhost:9090/api/v1/rules' | jq '.data.groups[].rules[] | select(.health!="ok")'
```

In the UIs:
- Prometheus `:9090` -> Status -> Targets / Rules / TSDB
- Alertmanager `:9093` -> current groups, silences
- Alloy `:12345` -> component graph, per-node throughput/errors
- Jaeger `:16686` -> search a recent trace; System Architecture tab
- Grafana `:3000` -> Explore each datasource returns data

## Key "is the pipeline healthy" queries

```promql
up == 0                                              # dead targets
rate(otelcol_exporter_send_failed_spans_total[5m])   # collector can't reach Jaeger
rate(otelcol_processor_refused_spans_total[5m])      # collector backpressure
prometheus_config_last_reload_successful             # 1 = good
prometheus_notifications_alertmanagers_discovered    # >=1
rate(loki_request_duration_seconds_count{status_code=~"5.."}[5m])
prometheus_tsdb_head_series                          # cardinality trend
```

`stack-alerts.yml` already alerts on most of these.

## Upgrades

1. Bump the tag in `docker-compose.yml` (one service at a time).
2. Read that project's CHANGELOG/UPGRADING for breaking config changes -
   Loki, the OTel Collector and Grafana break config across minors sometimes.
3. `make validate` (collector/prometheus/alertmanager).
4. `make pull && docker compose up -d <service>`.
5. Watch `make logs S=<service>` and its health endpoint.
6. Roll back = put the old tag back + `up -d`. Data volumes are compatible on
   downgrade **only** within the same major usually - check first.

Pinned versions are deliberate. Never use `:latest` in this file.

## Backups

| Volume | Contains | Backup approach | RPO comfort |
|---|---|---|---|
| `prometheus_data` | metrics TSDB | `promtool tsdb snapshot` via `POST /api/v1/admin/tsdb/snapshot` (needs `--web.enable-admin-api`), then copy `/prometheus/snapshots/...` | metrics are re-derivable-ish; low priority |
| `grafana_data` | dashboards created in UI, users, annotations | `docker run --rm -v v2_grafana_data:/v -v $PWD:/b alpine tar czf /b/grafana.tgz -C /v .` | **high** - or avoid the problem: keep dashboards as provisioned JSON in git |
| `loki_data` | logs + index | filesystem copy while stopped, or move to S3 | medium |
| `jaeger_data` | badger trace store | filesystem copy while stopped | low (traces are short-lived) |
| `alertmanager_data` | silences, notification state | filesystem copy | low |

Best practice: **dashboards, datasources, alert rules, and all config live in
this git repo**, so the only thing genuinely worth backing up is `grafana_data`
(if you edit dashboards in the UI) and whatever log/metric history you can't lose.

## Capacity / sizing (one box, rough)

| Component | Main driver | Watch |
|---|---|---|
| Prometheus RAM | **active series** (cardinality) | `prometheus_tsdb_head_series`; ~1-3 KB RAM/series. 1M series ≈ 2-4 GB |
| Prometheus disk | series x samples x retention | `--storage.tsdb.retention.size=20GB` caps it |
| Loki RAM | **active streams** + query concurrency | `loki_ingester_memory_streams` |
| Loki disk | ingest GB/day x 14d x ~0.1 (compression) | volume size |
| OTel Collector RAM | span throughput x batch size; tail-sampling buffer | `memory_limiter` protects it; give it 512 MB-1 GB |
| Jaeger/badger disk | spans stored x retention | move off badger past ~10-20 GB |

If Prometheus RAM climbs without bound: **Status -> TSDB**, look at "Top 10
label names by series" and "Top 10 metric names" - something is leaking
cardinality (usually a raw ID in a label). Fix at the source (drop the label in a
`metric_relabel_configs`, fix the instrumentation, or template the path).

## Incident quick paths

**"Everything is red in Grafana"**
-> is Prometheus up? `make ps`. Is `up` itself returning data? If Prometheus is
fine but all targets `DOWN`, suspect the `monitoring` network or the box's
firewall, not 12 services failing at once.

**"An alert fired, what now"**
-> alert annotation has `summary`/`description` and a link to the graph. Pivot:
metric -> dashboard for that `box`/`service_name` -> if it's an app, exemplar to a
trace -> trace to logs. `08` + `04` describe the jumps.

**"Traces stopped showing up"**
-> `rate(otelcol_receiver_accepted_spans[5m])` - is the app still sending?
`rate(otelcol_exporter_send_failed_spans_total[5m])` - can the collector reach
Jaeger? `docker logs otel-collector`.

**"Logs stopped"**
-> `docker logs alloy` (socket perms? loki unreachable?),
`curl localhost:3100/ready`, `loki_distributor_lines_received_total` rate.

**"Prometheus won't start after a config edit"**
-> it won't - it keeps the old config on a failed *reload*, but a failed *start*
means the on-disk config is bad. `make validate` shows the line. Fix, `up -d`.

## Security notes (before this leaves your laptop)

- Change `GRAFANA_ADMIN_PASSWORD` in `.env`.
- Nothing here has auth by default (Prometheus, Alertmanager, Loki, Jaeger,
  cAdvisor, node-exporter). **Do not publish these ports to the internet.** Bind
  to a private interface, put Grafana behind SSO / a reverse proxy, and firewall
  exporter ports to the observability box only.
- `otel-collector` `:4317/:4318` is an open ingest endpoint - restrict it to your
  app networks.
- The AWS key in `.env` (ECS profile) should be a **read-only** scoped IAM
  user/role. `.env` is gitignored - keep it that way.
