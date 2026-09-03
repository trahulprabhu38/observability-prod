# 01 - Metrics with Prometheus

## What Prometheus is

A **time-series database + scraper + rule engine** in one binary.

- **Scraper**: every `scrape_interval` (15s here) it does `GET /metrics` on each
  configured target and parses the text exposition format.
- **TSDB**: stores each sample as `(series identified by labels, timestamp,
  float64 value)`. Local disk. Retention capped by time **or** size
  (`15d` / `20GB` here, whichever hits first).
- **Rule engine**: every `evaluation_interval` it runs your recording &
  alerting rules; firing alerts go to Alertmanager.
- **HTTP API + PromQL**: Grafana and the UI at `:9090` query through this.

Prometheus is **not** clustered here and **not** long-term storage. That's fine
for one box. Scale-out (Thanos / Mimir / VictoriaMetrics) is a later problem.

## The exposition format (what a target serves)

```
# HELP http_requests_total Total HTTP requests.
# TYPE http_requests_total counter
http_requests_total{method="GET",status="200"} 12934
http_requests_total{method="POST",status="500"} 3
# TYPE process_resident_memory_bytes gauge
process_resident_memory_bytes 5.1234e+07
```

Metric **types**:

| Type | Meaning | You almost always... |
|---|---|---|
| **counter** | only goes up (resets to 0 on restart) | wrap in `rate()` |
| **gauge** | goes up and down (temp, memory, queue depth) | use directly, or `avg_over_time` |
| **histogram** | bucketed observations + `_sum` + `_count` | `histogram_quantile()` for percentiles |
| **summary** | client-side quantiles (can't aggregate across instances) | prefer histograms |

## This stack's scrape targets

Defined in `prometheus/prometheus.yml`.

| Job | Target | Gives you |
|---|---|---|
| `prometheus`, `grafana`, `loki`, `alloy`, `otel-collector`, `jaeger`, `alertmanager` | the stack itself | self-health (is the pipeline OK?) |
| `node` / `node-fleet` | node-exporter :9100 | host & LXC CPU/mem/disk/net/load/filesystem |
| `cadvisor` / `cadvisor-fleet` | cAdvisor :8080 | per-Docker-container CPU/mem/net/fs/restarts |
| `pushgateway` | :9091 | metrics pushed by batch jobs |
| `ecs-*` (commented) | YACE / discovery / ADOT | ECS/Fargate - see `05-ecs-metrics.md` |

### `static_configs` vs `file_sd_configs`

- `static_configs`: target list lives in `prometheus.yml`. Change = edit +
  reload.
- `file_sd_configs`: target list lives in a **separate file** that Prometheus
  re-reads on a timer (`refresh_interval`). Add a host = edit
  `prometheus/targets/node-fleet.yml`, **no reload needed**. This is how you grow
  the fleet. Example files are the `*.yml.example` ones - copy without the
  `.example` suffix.

Labels you attach in the target file (`box`, `kind`, `env`) ride along on every
metric from that target and become Grafana filter variables.

## node-exporter (hosts and LXC)

Runs on every Linux box. Exposes `node_*` metrics from `/proc` and `/sys`.

Key series:
- `node_cpu_seconds_total{mode=...}` - counter of CPU-seconds per mode. CPU busy %:
  `100 - (avg by(instance)(rate(node_cpu_seconds_total{mode="idle"}[5m])) * 100)`
- `node_memory_MemAvailable_bytes` / `node_memory_MemTotal_bytes`
- `node_filesystem_avail_bytes` / `node_filesystem_size_bytes` (filter
  `fstype!~"tmpfs|overlay|squashfs"`)
- `node_load1/5/15`
- `node_network_receive_bytes_total` / `_transmit_bytes_total`
- `node_disk_io_time_seconds_total` (disk saturation)

Dashboard to import: **1860 "Node Exporter Full"**.
LXC specifics and the "inside the container vs on the Proxmox host" decision:
`06-lxc-proxmox.md`.

## cAdvisor (Docker containers)

One container per Docker host. Reads the container runtime + cgroups. Exposes
`container_*` metrics **labelled by `name`, `image`, `id`**.

Key series:
- `rate(container_cpu_usage_seconds_total{name!=""}[5m])` - cores used
- `container_memory_working_set_bytes` - the number the OOM-killer watches
- `container_spec_memory_limit_bytes` - the limit (0 = unlimited)
- `container_network_receive_bytes_total` / `_transmit_bytes_total`
- `container_fs_usage_bytes`
- `container_last_seen` - `time() - container_last_seen > 60` => container gone

Dashboard: **19792**. Alerts: `prometheus/rules/container-alerts.yml`.

> cAdvisor is a bit heavy and its metrics are verbose. That's normal. If it's too
> much, drop `--store_container_labels` and use
> `--docker_only --housekeeping_interval=15s`.

## Pushgateway (batch / cron jobs)

A job that runs for 4 seconds can't be scraped. Instead it **pushes** its final
metrics to Pushgateway, which holds them until Prometheus scrapes it.

Push from a job:

```bash
cat <<EOF | curl --data-binary @- http://pushgateway:9091/metrics/job/nightly_backup/instance/db01
# TYPE backup_duration_seconds gauge
backup_duration_seconds 143.2
# TYPE backup_last_success_timestamp_seconds gauge
backup_last_success_timestamp_seconds $(date +%s)
EOF
```

Then alert on staleness:
`time() - backup_last_success_timestamp_seconds > 90000` (no successful backup in
25h).

Gotchas:
- Pushgateway **keeps the last value forever** until you `DELETE` it or it
  restarts. It is not a metrics history - it's a "last known state" board.
  `--web.enable-admin-api` (set in compose) lets you
  `curl -X DELETE http://pushgateway:9091/metrics/job/nightly_backup`.
- The scrape job uses `honor_labels: true` so the job's own `job`/`instance`
  win over the pushgateway's.
- Don't use it for anything that could be scraped normally. It's a workaround.

## PromQL - the 10 patterns you need

```promql
# 1. per-second rate of a counter (ALWAYS rate() a counter)
rate(http_requests_total[5m])

# 2. sum away labels you don't care about
sum by (service) (rate(http_requests_total[5m]))

# 3. error ratio
sum(rate(http_requests_total{status=~"5.."}[5m]))
  / sum(rate(http_requests_total[5m]))

# 4. p95 latency from a histogram
histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket[5m])))

# 5. is a target down
up == 0

# 6. top 5 memory-hungry containers
topk(5, container_memory_working_set_bytes{name!=""})

# 7. predict disk full within 24h
predict_linear(node_filesystem_avail_bytes{mountpoint="/"}[6h], 24*3600) < 0

# 8. value 1h ago (compare now vs then)
node_memory_MemAvailable_bytes offset 1h

# 9. restarts in the last hour
increase(container_start_time_seconds{name!=""}[1h])

# 10. join two metrics on shared labels
container_memory_working_set_bytes / on(name) container_spec_memory_limit_bytes
```

`rate()` needs a **range vector** (`[5m]`) and at least 2 samples in the window,
so pick a window >= 4x scrape interval (>= 1m here; 5m is safe).

## Recording rules vs alerting rules

Both live in `prometheus/rules/*.yml`, both evaluated every 15s.

- **Recording rule**: precompute an expensive query into a new series
  (`record: service:error_rate:5m`). Dashboards/alerts then read the cheap
  pre-rolled series. Naming convention: `level:metric:operation`.
- **Alerting rule**: `alert:` + `expr:` + `for:` (how long it must be true
  before firing) + `labels:` (severity, routed on by Alertmanager) +
  `annotations:` (human text, supports templating with `{{ $labels.x }}` and
  `{{ $value }}`).

See them in this repo:
`rules/infra-alerts.yml`, `rules/container-alerts.yml`, `rules/stack-alerts.yml`.

## remote-write (how OTel metrics get in)

The OpenTelemetry Collector doesn't expose `/metrics` for Prometheus to scrape
its app metrics - it **pushes** them via the Prometheus remote-write protocol to
`http://prometheus:9090/api/v1/write`. That endpoint only exists because the
compose command has `--web.enable-remote-write-receiver`. The span-metrics
(`traces_spanmetrics_*`) arrive this way.

## Operating it

```bash
make validate            # promtool check config + rules
make reload-prometheus    # POST /-/reload after editing prometheus.yml or rules
make prom-targets         # table of every target and its health
```

- **Status -> Targets** in the UI (`:9090`) - anything not `UP` shows the error.
- **Status -> Rules** - shows rule health and last evaluation.
- **Status -> TSDB** - series count, biggest metrics (cardinality hunting).
- **Alerts** tab - which alerts are `inactive` / `pending` / `firing`.

## Common problems

| Symptom | Cause / fix |
|---|---|
| target `DOWN`, "connection refused" | wrong port, container not up, not on `monitoring` network, firewall |
| target `DOWN`, "context deadline exceeded" | exporter too slow / `scrape_timeout` too low |
| metric missing in Grafana but target UP | wrong metric name, or a relabel dropped it; check `/metrics` directly |
| Prometheus RAM climbing forever | cardinality explosion - **Status -> TSDB**, find the offending label |
| `out of order sample` on remote-write | two writers sending the same series, or clock skew |
| rules not firing | `for:` not elapsed, or `expr` returns nothing - test it in the UI first |
