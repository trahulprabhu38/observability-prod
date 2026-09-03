# 00 - Observability from scratch: the mental model

Read this first. It explains *what* every box in this stack is for and *why*
they fit together, so the config files stop looking like magic.

---

## 1. What "observability" actually means

You have systems (containers, hosts, apps). They emit **telemetry**. You want to
answer, quickly:

- **Is it broken? How badly?** -> alerting
- **What changed?** -> dashboards / trends
- **Why is this one request slow / failing?** -> drill into a single event

Three kinds of telemetry cover almost everything. They are the **three pillars**:

| Pillar | Question it answers | Shape of the data | Store here |
|---|---|---|---|
| **Metrics** | "how much / how many / how fast", over time | numbers sampled on a schedule, with labels | **Prometheus** |
| **Logs** | "what exactly happened at 14:03:22" | timestamped text lines, with labels | **Loki** |
| **Traces** | "where did this one request spend its time" | a tree of timed spans across services | **Jaeger** |

They are **complementary**, not competing. Typical flow when something breaks:

```
metric alert fires  ->  dashboard shows which service / box  ->
trace shows which span is slow / erroring  ->  logs for that trace show the stack trace
```

This stack wires those jumps together so you can click from one to the next
(exemplars, derived fields, trace-to-logs). That correlation is the whole point
of running them in one Grafana.

---

## 2. Push vs pull (why Prometheus "scrapes")

- **Pull**: the monitoring server periodically calls `GET /metrics` on each
  target. Prometheus works this way. Targets just expose a text endpoint; they
  don't need to know where Prometheus is. Prometheus knows what *should* be up,
  so a missing target is itself a signal (`up == 0`).
- **Push**: the source sends data to a collector. Logs and traces work this way
  (they're events, you can't "poll" for them). Batch jobs also push metrics
  (they exit before anyone can scrape them) - that's what **Pushgateway** is for.

This stack uses **pull for infra metrics** (node-exporter, cAdvisor) and **push
for app telemetry** (OTLP to the OpenTelemetry Collector, Docker logs to Alloy).

---

## 3. Labels and the cardinality trap (the #1 thing beginners break)

Every metric / log stream / span is identified by its **label set**:

```
http_requests_total{service="api", method="GET", route="/users/:id", status="200"}
```

Each unique combination of label values is a separate **series** (Prometheus) or
**stream** (Loki). Memory and query cost scale with the **number of series**.

**Never put unbounded values in a label**: user IDs, email addresses, raw URLs
with IDs in them (`/users/12345`), request IDs, trace IDs, timestamps, full error
messages. One label like `user_id` can create millions of series and fall over
the whole stack ("cardinality explosion").

Rules of thumb:
- A label is fine if you can list all its possible values on a napkin
  (`method`, `status_code`, `env`, `service`, `route-template`).
- High-cardinality detail belongs **in the log body** (grep it with LogQL) or
  **as a span attribute** (searchable in Jaeger), not as a metric label.
- Templates, not raw paths: `/users/:id` not `/users/12345`. The OTel Collector
  and your instrumentation should do this collapsing.

---

## 4. This stack, one diagram

```
                    ┌────────────── APPLICATIONS (any box) ──────────────┐
                    │  OpenTelemetry SDK  --OTLP :4317/:4318-->           │
                    │  (traces, metrics, logs; sets service.name,        │
                    │   deployment.environment, service.version)         │
                    └───────────────────────┬───────────────────────────┘
                                            │
  Docker stdout ─────────────┐              │
  (/var/run/docker.sock)     ▼              ▼
                       ┌──────────┐   ┌───────────────────┐
                       │  ALLOY   │   │  OTEL COLLECTOR    │
                       │ (logs)   │   │  memory_limiter ─► │
                       └────┬─────┘   │  redact ─► batch   │
                            │         │  spanmetrics ┐     │
   scrape /metrics          │         └───┬───────┬──┴─────┘
   (pull)                   │ logs        │traces │metrics
   ┌───────────────┐        │             │       │
   │ node-exporter │        ▼             ▼       ▼
   │ cAdvisor      │   ┌────────┐   ┌────────┐  ┌────────────┐
   │ pushgateway   │──►│  LOKI  │   │ JAEGER │  │ PROMETHEUS │◄── scrapes
   │ ECS exporters │   │ (logs) │   │(traces)│  │ (metrics)  │    all exporters
   │ stack self    │   └───┬────┘   └───┬────┘  └─────┬──────┘    + span-metrics
   └───────────────┘       │            │            │           via remote-write
                           ▼            ▼            ▼
                       ┌──────────────────────────────────────┐
                       │              GRAFANA                  │
                       │  Prometheus + Loki + Jaeger datasrcs  │
                       │  dashboards · Explore · correlation   │
                       └──────────────────┬───────────────────┘
                                          │ rule fires
                                    ┌─────▼──────┐
                                    │ ALERTMANAGER│ -> Slack / PagerDuty / webhook
                                    └─────────────┘
```

Prometheus also evaluates alerting rules every 15s and hands firing alerts to
Alertmanager, which groups/routes/dedupes them into notifications.

---

## 5. Why these specific tools

| Slot | Choice | Why not the alternative |
|---|---|---|
| Metrics DB | **Prometheus** | The de-facto standard; PromQL; huge exporter ecosystem. (Alt: VictoriaMetrics/Mimir for scale - overkill now.) |
| Metrics: hosts/LXC | **node-exporter** | Canonical Linux exporter; one dashboard (1860) covers it. |
| Metrics: Docker | **cAdvisor** | Per-container CPU/mem/net/fs with zero app changes. |
| Metrics: batch | **Pushgateway** | The only sane way to get metrics out of a job that exits. |
| Logs | **Loki** | Cheap: indexes labels, not content. Same label model as Prometheus, one query UX in Grafana. (Alt: ELK - far heavier.) |
| Log shipper | **Alloy** | One agent, native Docker discovery + Loki writer. It *is* an OTel Collector distro, so the concepts transfer. |
| Traces pipeline | **OpenTelemetry Collector** | Vendor-neutral; receivers/processors/exporters; generates span-metrics. |
| Traces store/UI | **Jaeger** | Mature trace UI, service map, "Monitor" (RED) tab; speaks OTLP natively. (Alt: Tempo - we deliberately dropped it in v2.) |
| Dashboards | **Grafana** | Talks to all three; correlation features; provisioning as code. |
| Alert routing | **Alertmanager** | Grouping / inhibition / silences / routing tree - Prometheus's companion. |

---

## 6. What runs where

- **Observability box**: everything in `docker-compose.yml`. One box.
- **Every other host / LXC**: just `node-exporter` (OS metrics) and, if it runs
  Docker, a `cAdvisor` container. They expose `/metrics`; Prometheus reaches in
  and scrapes. See `06-lxc-proxmox.md`.
- **Docker hosts**: same, plus you can run an Alloy there too if you want its
  container logs (or ship them to the central Loki some other way).
- **ECS**: no agent you SSH into - use CloudWatch (YACE), task discovery, or an
  ADOT sidecar. See `05-ecs-metrics.md`.
- **Applications**: an OpenTelemetry SDK pointed at the collector's OTLP port.
  See `07-instrumenting-apps.md`.

---

## 7. Suggested learning order

1. This file.
2. `01-metrics-prometheus.md` + get `up`, node-exporter and cAdvisor green in
   Prometheus **Status -> Targets**. Learn 5 PromQL queries.
3. `04-grafana-alerting.md` - add the Prometheus datasource, import dashboard
   1860, wire one alert end-to-end to a webhook.
4. `02-logs-loki-alloy.md` - see container logs in Grafana Explore, learn LogQL.
5. `03-traces-otel-jaeger.md` - instrument the sample app, watch a trace appear
   in Jaeger, click an exemplar from a metric to its trace.
6. `05` / `06` for the environments you actually run.
7. `08-operations-runbook.md` when you operate it day to day.

Then `resources.md` for books, courses and deep dives to go beyond this repo.
