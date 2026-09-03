# Observability stack v2

Built from scratch. **Tempo is gone**; traces now run on **OpenTelemetry
Collector + Jaeger**. Storage is **local disk** (no S3/IAM) so it runs anywhere
with one command.

```
METRICS   Prometheus  <-  node-exporter (hosts/LXC) · cAdvisor (Docker) ·
                          Pushgateway (batch jobs) · ECS (CloudWatch / task / ADOT)
LOGS      Alloy  ->  Loki
TRACES    OpenTelemetry Collector  ->  Jaeger   (+ RED span-metrics -> Prometheus)
UI        Grafana  +  Alertmanager
```

---

## Quick start

```bash
cd v2
cp .env.example .env          # then edit GRAFANA_ADMIN_PASSWORD
make up                       # or: docker compose up -d
make ps
```

Open:

| URL | What |
|---|---|
| http://localhost:3000  | **Grafana** (admin / value from `.env`) |
| http://localhost:9090  | Prometheus (Status -> Targets first) |
| http://localhost:9093  | Alertmanager |
| http://localhost:16686 | Jaeger UI |
| http://localhost:12345 | Alloy pipeline UI |
| http://localhost:55679/debug/tracez | OTel Collector live spans |

Send an app's telemetry here: `OTEL_EXPORTER_OTLP_ENDPOINT=http://<this-host>:4317`

---

## Read the docs (they're the point of this repo)

Work through them in order - each is standalone and explains the *why*, not just
the *how*.

| Doc | Covers |
|---|---|
| [`docs/00-overview.md`](docs/00-overview.md) | the mental model: 3 pillars, push vs pull, cardinality, full data-flow diagram, learning order |
| [`docs/01-metrics-prometheus.md`](docs/01-metrics-prometheus.md) | Prometheus internals, exposition format, node-exporter, cAdvisor, Pushgateway, 10 PromQL patterns, recording/alerting rules, remote-write |
| [`docs/02-logs-loki-alloy.md`](docs/02-logs-loki-alloy.md) | why Loki indexes labels not text, the Alloy pipeline component-by-component, LogQL, retention, storage |
| [`docs/03-traces-otel-jaeger.md`](docs/03-traces-otel-jaeger.md) | spans/traces, context propagation, OTLP, the Collector pipeline, span-metrics = RED, head vs tail sampling, Jaeger, correlation |
| [`docs/04-grafana-alerting.md`](docs/04-grafana-alerting.md) | provisioning, Explore vs dashboards, template variables, Prometheus-vs-Grafana alerting, Alertmanager route tree / grouping / inhibition / silences, one alert end-to-end |
| [`docs/05-ecs-metrics.md`](docs/05-ecs-metrics.md) | four ways to get ECS/Fargate metrics (YACE/CloudWatch, task discovery, ADOT sidecar, EC2 daemon), IAM, trade-offs, what to pick |
| [`docs/06-lxc-proxmox.md`](docs/06-lxc-proxmox.md) | node-exporter inside a CT vs on the PVE host, the lxcfs/cgroup caveats table, prometheus-pve-exporter, the fleet pattern |
| [`docs/07-instrumenting-apps.md`](docs/07-instrumenting-apps.md) | OTel SDK env vars, auto-instrumentation per language, span attribute hygiene, structured+correlated logs, batch jobs, a new-service checklist |
| [`docs/08-operations-runbook.md`](docs/08-operations-runbook.md) | reloads, health-check tour, upgrades, backups, capacity sizing, incident quick-paths, security notes |
| [`docs/resources.md`](docs/resources.md) | curated external reading/watching + a 2-week self-study plan |

---

## Folder layout

```
v2/
├── docker-compose.yml          # the whole stack (one box)
├── .env.example                # copy to .env
├── Makefile                    # make help
│
├── prometheus/
│   ├── prometheus.yml          # scrape config; ECS jobs commented, ready to enable
│   ├── targets/                # file_sd fleet lists (*.yml.example -> drop .example)
│   └── rules/                  # infra / container / stack alerts + RED recording rules
├── alertmanager/alertmanager.yml   # route tree, inhibition, receivers (webhook placeholders)
├── alloy/config.alloy          # Docker stdout -> Loki
├── loki/loki.yml               # single-binary, local filesystem, 14d retention
├── otel-collector/config.yaml  # OTLP in -> Jaeger + Prometheus(spanmetrics) + Loki
│
├── grafana/provisioning/
│   ├── datasources/datasources.yml  # Prometheus + Loki + Jaeger (+ Infinity, opt-in CloudWatch)
│   └── dashboards/                  # "Stack Health" + community + dashboards imported from prod (see its README)
│
├── ecs/
│   ├── yace/config.yml         # CloudWatch exporter config (compose profile: ecs)
│   ├── ecs-discovery/README.md # task-level scraping
│   └── adot/README.md          # sidecar push model
├── lxc/node-exporter-lxc.md    # copy-paste install for a Proxmox CT
├── scripts/fetch-dashboards.sh # pull community dashboards into provisioning
└── docs/                       # ← start here
```

---

## Common commands

```bash
make help              # list everything
make validate          # lint prometheus + alertmanager + otel configs
make reload-prometheus # after editing prometheus.yml / rules
make reload-alloy      # after editing config.alloy
make prom-targets      # table of scrape targets + health
make logs S=jaeger     # tail one service
make ecs-up            # bring up the ECS/CloudWatch exporter too
make down / make nuke  # stop / stop+wipe volumes
```

## Growing the fleet

- **Another host or LXC**: install node-exporter (`lxc/node-exporter-lxc.md`),
  add a line to `prometheus/targets/node-fleet.yml`. No reload needed.
- **Another Docker host**: run a cAdvisor container, add it to
  `prometheus/targets/cadvisor-fleet.yml`.
- **ECS**: `docs/05-ecs-metrics.md`.
- **An application**: `docs/07-instrumenting-apps.md` - point its OTel SDK at
  `:4317`.

## Notes

- Versions in `docker-compose.yml` are **pinned** on purpose. Upgrade
  deliberately (`docs/08`), never `:latest`.
- Nothing here has authentication by default. **Do not expose these ports to the
  internet** - see the security section in `docs/08-operations-runbook.md`.
- The old stack is untouched in `../prod-prometheus-setup/` for reference (its
  Loki S3 config is a useful example if you outgrow local disk).
