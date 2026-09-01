# prod-prometheus-setup

Central **OpenTelemetry-based** observability stack: **metrics + logs + traces**,
all collected through one OTel pipeline and viewed in one Grafana.
Traces and logs are stored in **S3** (`ap-south-1`) so they never grow the local
disk; metrics stay local in Prometheus (15 d / 40 GB cap).

One stack serves **every environment** (dev / staging / prod). There is no separate
Grafana / Prometheus / Loki / Tempo per environment — telemetry is separated
**logically, by an `env` tag** that every signal carries, and Grafana dashboards
filter on that tag. See [Environments](#environments-dev--staging--prod).

---

## Architecture

### High level

```
                            APPLICATIONS (dev / staging / prod boxes)
                     OpenTelemetry SDK  ── OTLP :4317 gRPC / :4318 HTTP ──┐
                     (traces · metrics · logs, resource attrs incl.       │
                      deployment.environment, service.version)            │
                                                                          ▼
  docker stdout ─────────────────────────────────────────►  ┌───────────────────────────┐
  (per box, via /var/run/docker.sock)                        │   GRAFANA ALLOY           │
                                                             │   (OpenTelemetry          │
  scrape targets (cAdvisor :8085, node-exporter :9100, ─────►│    Collector distro)      │
   blackbox, pushgateway, stack self-metrics)                │                           │
                                                             │  receive → limit → redact │
                                                             │  PII → template routes →  │
                                                             │  spanmetrics + tail-      │
                                                             │  sample → export          │
                                                             └───┬───────┬───────┬───────┘
                                        traces (sampled) OTLP │       │ metrics │ logs OTLP
                                                              ▼       ▼ (RW)     ▼
                                                   ┌────────┐  ┌────────────┐  ┌────────┐
                                                   │ TEMPO  │  │ PROMETHEUS │  │  LOKI  │
                                                   │ traces │  │  metrics   │  │  logs  │
                                                   │  + SG  │──┤  (local,   │  │        │
                                                   │  gen   │RW│  15d/40GB) │  │        │
                                                   └───┬────┘  └─────┬──────┘  └───┬────┘
                                       s3://valura-       │  (also scrapes         │  s3://valura-
                                       tempo-traces  ◄────┘   its own targets)     └──►  loki-logs
                                                              │        │        │
                                                              ▼        ▼        ▼
                                                   ┌──────────────────────────────────┐
                                                   │            GRAFANA               │
                                                   │  Prometheus · Loki · Tempo DS    │
                                                   │  exemplars, trace⇄log⇄metric     │
                                                   │  $env variable scopes every panel│
                                                   └──────────────────────────────────┘
```

### OpenTelemetry's role

OpenTelemetry is the backbone of this stack, not an add-on:

| OTel concept              | Realised here as                                                                 |
|---------------------------|---------------------------------------------------------------------------------|
| **OTel Collector**        | **Grafana Alloy** (`alloy/config.alloy`) — a Collector *distribution*. Every `otelcol.receiver.*` / `otelcol.processor.*` / `otelcol.connector.*` / `otelcol.exporter.*` block is upstream OpenTelemetry Collector code with Alloy's config syntax. |
| **OTLP**                  | The single ingest contract — `otelcol.receiver.otlp` on `:4317` (gRPC) and `:4318` (HTTP). Traces, metrics and logs all arrive this way. |
| **OTel SDKs**             | Applications instrument with language OTel SDKs and export OTLP to Alloy.       |
| **Semantic conventions**  | `deployment.environment`, `service.name`, `service.version`, `http.route`, … drive the `env` tag, deploy markers and RED-metric dimensions. |
| **OTTL** (transform lang) | PII redaction and route templating (`otelcol.processor.transform`).            |
| **Span-to-metrics**       | `otelcol.connector.spanmetrics` generates the RED catalogue from spans.        |
| **Tail sampling**         | `otelcol.processor.tail_sampling` keeps 100 % errors / slow + a 10 % baseline. |

Why Alloy and not a standalone `otel/opentelemetry-collector-contrib` container:
the same binary also does Prometheus-style scraping (`prometheus.scrape`) and
Docker log tailing (`loki.source.docker`), and has native `prometheus.remote_write`
/ `loki.write` components — so one agent covers all three signals plus infra
metrics and container logs. Apps see a standard OTLP endpoint either way; the
config translates back to vanilla Collector almost 1:1 if we ever swap.

### Ingestion layer — what feeds Alloy

| Source                          | Mechanism                                              | Signals              |
|---------------------------------|------------------------------------------------------|----------------------|
| Application OTel SDKs            | OTLP push → `:4317` / `:4318`                          | traces, metrics, logs|
| Docker container stdout/stderr   | `discovery.docker` + `loki.source.docker` (per box)   | logs                 |
| cAdvisor (`:8085` fleet, `:8080` local) | Prometheus scrape                              | container metrics    |
| node-exporter (`:9100`)         | Prometheus scrape                                      | host metrics         |
| blackbox-exporter (`:9115`)     | Prometheus scrape of `/probe`                          | synthetic / SLO      |
| pushgateway (`:9091`)           | Prometheus scrape (batch jobs push in)                 | batch metrics        |
| Stack self-metrics              | Prometheus scrape of prometheus/grafana/loki/tempo/alloy | health              |

### Collector pipeline (`alloy/config.alloy`), stage by stage

```
 OTLP in ─► memory_limiter ─┬─ traces ─► transform "pii"  ─► transform "route_template" ─┬─► spanmetrics "red" ─► prometheus RW
 (4317/4318)                │            (OTTL: drop keys,     (OTTL: /123 → /:id,        │
                            │             mask PAN/Aadhaar/     UUID → /:uuid, hashes)    └─► tail_sampling ─► batch ─► OTLP ─► Tempo
                            │             passport/email/                                     (100% err, 100% >1s,
                            │             phone/JWT in attrs                                   10% baseline)
                            │             + log body)
                            │
                            ├─ metrics ─────────────────────────────────────────────────────► prometheus RW  (http://prometheus:9090/api/v1/write)
                            │
                            └─ logs ────► transform "pii" ─────────────────────────────────► OTLP HTTP ─► Loki (/otlp)

 docker logs ─► discovery.relabel ─► loki.source.docker ─► loki.process (static label env) ─► loki.write ─► Loki (/loki/api/v1/push)
```

Key points:

- **spanmetrics runs on 100 % of spans, before tail sampling**, so RED rates stay
  accurate even though only ~10 % of traces are stored. Dimensions:
  `service.version`, `http.request.method`, `http.route`, `http.response.status_code`
  (add `deployment.environment` — see [Environments](#environments-dev--staging--prod)).
- **Route templating** collapses high-cardinality path IDs (`/portfolio/123` →
  `/portfolio/:id`) before they become metric labels or span names.
- **PII redaction happens once, up front**, and covers span/resource/log
  attributes *and* the free-text log body (IFSCA / GIFT City — PAN, Aadhaar,
  passport, email, phone, `Authorization`, cookies, account & broker tokens).
- `livedebugging` is enabled — inspect live data at the Alloy UI (`:12345`).

### Storage layer

| Backend       | Data   | Location                                  | Retention                              |
|---------------|--------|-----------------------------------------|----------------------------------------|
| Prometheus    | metrics| local TSDB (`prometheus_data`)           | 15 d **or** 40 GB, whichever first     |
| Loki          | logs   | **S3** `valura-loki-logs` (ap-south-1)   | 336 h (14 d); S3 lifecycle backstop 17 d |
| Tempo         | traces | **S3** `valura-tempo-traces` (ap-south-1)| 168 h (7 d); S3 lifecycle backstop 10 d |

Only WAL / active index / caches touch local disk on Loki and Tempo. AWS creds
come from `.env` (scoped IAM user `valura-observability-s3`, S3 verbs on those two
buckets only).

**Tempo metrics-generator** remote-writes back into Prometheus: `service-graphs`
(powers the Grafana service map / node graph) and `local-blocks` (powers TraceQL
metrics). Span-metrics/RED are *not* duplicated here — Alloy produces the richer
version upstream.

### Visualization & correlation layer

Grafana (`grafana/provisioning/datasources/datasource.yml`) wires all three data
sources for bi-directional drilldown:

| From        | To          | How                                                                      |
|-------------|-------------|------------------------------------------------------------------------|
| metric      | trace       | Prometheus **exemplars** carry `trace_id` → "View trace" in Tempo       |
| log line    | trace       | Loki **derived field** regex extracts `trace_id` → Tempo               |
| trace/span  | logs        | Tempo `tracesToLogsV2` → Loki, time-shifted ±5 m, filtered by trace ID  |
| trace/span  | metrics     | Tempo `tracesToMetrics` → Prometheus                                    |
| trace       | service map | Tempo `serviceMap` + `nodeGraph` off Prometheus service-graph metrics   |

Provisioned dashboards (`grafana/provisioning/dashboards/json/`): 17346 (Traefik),
19792 (cAdvisor). Plugins: `grafana-lokiexplore-app`, `grafana-exploretraces-app`.

---

## Design decisions

| Decision | Rationale | Trade-off / revisit when |
|---|---|---|
| **Grafana Alloy** as the only agent | one binary for OTLP + scraping + docker logs + remote-write; fewer moving parts than Collector + Promtail + exporters | slightly Grafana-specific config; upstream Collector features land in Alloy on a lag |
| **Single stack, `env` tag** for all environments | ⅓ the cost & ops surface of three stacks for this fleet size | no hard isolation, global retention, coarse access control — [details](#trade-offs--when-to-split) |
| **Metrics local, logs+traces in S3** | metrics are small & high-query; logs/traces are bulky & write-heavy — S3 keeps the box disk flat and cheap | S3 latency on cold trace/log queries; needs the scoped IAM key |
| **Tail sampling** (100 % err / 100 % >1 s / 10 % rest) | keep every "interesting" trace, pay to store ~10 % of the boring ones | sampled-away traces are gone; rates come from spanmetrics instead |
| **spanmetrics before sampling** | RED rates/latencies stay statistically correct | extra CPU in Alloy proportional to span volume |
| **Route templating in the collector** | stops `/{id}` paths exploding label cardinality in Prometheus & Tempo | a genuinely dynamic route needs a rule added |
| **PII redaction in the collector, not the app** | one enforced choke point for IFSCA / GIFT City compliance regardless of who instruments | regex masking is best-effort on free text; keep patterns current |
| **hub-and-spoke** (agents only on app boxes) | app boxes stay cheap; one place to upgrade the stack | the observability box is a single point of failure for ingestion |

---

## Components

| Service            | Port  | Role                                              | Storage                              |
|--------------------|-------|--------------------------------------------------|--------------------------------------|
| grafana            | 3000  | Dashboards / Explore / Drilldown                 | `grafana_data`                       |
| prometheus         | 9090  | Metrics TSDB (remote-write + exemplars)          | local, **15 d or 40 GB**             |
| loki               | 3100  | Logs                                             | **S3** `valura-loki-logs`, 14 d      |
| tempo              | 3200  | Traces + service-graph / span-metrics generator | **S3** `valura-tempo-traces`, 7 d    |
| alloy              | 12345 | OpenTelemetry Collector. **OTLP in: 4317 / 4318**| —                                    |
| node-exporter      | 9100  | Host metrics (observability box)                 | —                                    |
| cadvisor           | 8080  | Container metrics (observability box)            | —                                    |
| pushgateway        | 9091  | Batch-job metrics                                | —                                    |
| blackbox-exporter  | 9115  | HTTP/TCP/ICMP probing of public endpoints (SLOs)| —                                    |
| alertmanager       | 9093  | Alert routing (optional — commented out)         | `alertmanager_data`                  |

All services share the `monitoring` bridge network and are defined in `docker-compose.yml`.

---

## Deployment topology

Hub-and-spoke. One box runs everything in this repo; every other box runs only
lightweight agents that report back to it.

```
                       ┌─────────────────────────── observability box (env=infra, 10.200.2.52) ──┐
                       │  grafana · prometheus · loki · tempo · alloy · pushgateway              │
                       │  node-exporter · cadvisor · blackbox-exporter                            │
                       └───▲───────────▲───────────────────────────────────▲─────────────────────┘
        scrape :8085 /9100 │           │ OTLP :4317 (traces/metrics/logs)   │ scrape :8085
                           │           │                                    │
        ┌──────────────────┴──┐   ┌────┴───────────────────┐   ┌────────────┴─────────────┐
        │  dev box(es)        │   │  staging box(es)       │   │  prod box(es)            │
        │  env=dev            │   │  env=staging           │   │  env=prod                │
        │  cadvisor :8085     │   │  cadvisor :8085        │   │  cadvisor :8085          │
        │  app → OTLP,        │   │  app → OTLP,           │   │  app → OTLP,             │
        │  deployment.        │   │  deployment.           │   │  deployment.            │
        │  environment=dev    │   │  environment=staging   │   │  environment=prod       │
        └─────────────────────┘   └────────────────────────┘   └──────────────────────────┘
```

**On the observability box** — the full `docker compose up -d` from this repo.

**On every app box (dev / staging / prod / edge)** — no Grafana, no Prometheus. Just:

| Agent                | How                                                      | Consumed by                          |
|----------------------|---------------------------------------------------------|--------------------------------------|
| cAdvisor `:8085`     | `scripts/cadvisor-rollout.sh` or `cadvisor-remote/`     | Prometheus `cadvisor-fleet` job      |
| node-exporter `:9100`| optional, add to the fleet job                          | Prometheus                           |
| app OTel SDK         | point at `http://<observability-box>:4317`, set `deployment.environment` | Alloy → Tempo / Prometheus / Loki |

**Firewall** — app boxes must reach the observability box on `4317/4318` (OTLP);
the observability box must reach each app box on `8085` (and `9100` if node-exporter
is in the fleet). Nothing else needs to be open between boxes.

---

## Environments (dev / staging / prod)

### Why a tag instead of a stack per environment

We run **one** Grafana / Prometheus / Loki / Tempo. Standing up three copies would
triple the cost and the operational surface for a fleet this size. Instead, every
metric, log line and trace is stamped with an **`env` tag**, and Grafana scopes
each dashboard to one environment with a template variable. Isolation is logical,
not physical — see [Trade-offs](#trade-offs--when-to-split).

### The canonical tag

| Signal      | Carrier                                             | Where it is set                                              |
|-------------|----------------------------------------------------|-------------------------------------------------------------|
| Metrics     | Prometheus label `env`                              | static `labels:` on scrape targets; spanmetrics dimension  |
| Logs        | Loki stream label `env`                             | Alloy `stage.static_labels` / OTLP resource attr           |
| Traces      | resource attribute `deployment.environment`         | app OTel SDK (`OTEL_RESOURCE_ATTRIBUTES`)                   |

Apps only ever set **`deployment.environment`** (OTel semantic convention). Alloy
maps that resource attribute onto the `env` label for metrics and logs, so
dashboards can use a single `env` variable across all three data sources.

### Tag values

| `env` value | Boxes                                            | Notes                                    |
|-------------|-------------------------------------------------|------------------------------------------|
| `dev`       | `valura-dev` (10.200.2.51)                       |                                          |
| `staging`   | `uae-staging` (10.200.2.56), `valura-ind-stg` (10.200.2.57) | two regions, one env tag       |
| `prod`      | `dubai` (86.106.26.45), `prod-uae` (10.200.2.54) | `prod-uae` unreachable during setup      |
| `infra`     | `observability` (10.200.2.52)                    | the monitoring box monitoring itself     |
| `edge`      | edge proxy box — IP TBD                          | Traefik / blackbox source                |

Pick **one** value per box and never reuse it. If you split `staging` by region
later, add a second label (`region=uae` / `region=ind`) rather than overloading `env`.

### How each signal gets the tag

**1 — Fleet container metrics** (`prometheus/prometheus.yml`, `cadvisor-fleet` job).
Already wired: every target sets `env` in its static `labels:` block.

```yaml
- targets: ["10.200.2.51:8085"]
  labels: {box: valura-dev,     env: dev}
- targets: ["10.200.2.56:8085"]
  labels: {box: uae-staging,    env: staging}
- targets: ["86.106.26.45:8085"]
  labels: {box: dubai,          env: prod}
```

Add a box → add a line with its `env`. Same pattern for a `node-exporter-fleet` job.

**2 — App metrics / traces / RED metrics** (`alloy/config.alloy`).
The app sets the resource attribute; Alloy turns it into a metric label and a
spanmetrics dimension:

```bash
# in the application container
OTEL_EXPORTER_OTLP_ENDPOINT=http://<observability-box>:4317
OTEL_SERVICE_NAME=my-service
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=staging,service.version=1.4.2
```

Wiring to add in `alloy/config.alloy`:

- a `otelcol.processor.resource` (or `transform`) step that copies
  `deployment.environment` → `env` on metrics and logs;
- `dimension { name = "deployment.environment" }` on
  `otelcol.connector.spanmetrics "red"` so RED rates are per-environment;
- on `otelcol.exporter.prometheus`, promote only the `env` resource attribute to a
  label (not `resource_to_telemetry_conversion = true`, which would explode cardinality).

**3 — Container logs** (`alloy/config.alloy`, `loki.process "containers"`).
Today this hard-codes `env = "production"`. Replace the static value with one
sourced per box — either an env var on the Alloy container
(`stage.static_labels { values = { env = env("ENV") } }`) or a Docker label on
each app container lifted with `stage.labels`.

**4 — OTLP logs** → Loki keeps `deployment.environment` as a resource attribute;
add `env` to `limits_config.otlp_config.resource_attributes` in `loki/loki.yml` so
it is promoted to a stream label and matches the metrics label name.

**5 — Blackbox / SLO probes** (`blackbox/targets.json`).
Add `env` to each target group's `labels` so probe SLOs are per-environment:

```json
{ "labels": { "module": "http_2xx", "tier": "public", "env": "prod" },
  "targets": ["https://app.example.com/health"] }
```

**6 — Traces** need no mapping — query `deployment.environment` directly in TraceQL:
`{ resource.deployment.environment = "prod" }`.

### Grafana: the `$env` variable

Every dashboard gets a **templating variable** `env`:

- **Type** query, **Data source** Prometheus, **Query** `label_values(env)`
- Optionally `Include All`, but default to a single value so panels never mix envs.

Panel queries then filter on it:

| Data source | Filter                                                       |
|-------------|-------------------------------------------------------------|
| Prometheus  | `sum(rate(http_requests_total{env="$env"}[5m]))`           |
| Loki        | `{env="$env"} \|= "error"`                                 |
| Tempo       | `{ resource.deployment.environment = "$env" }`             |

Because the tag name is consistent, exemplar jumps (metric → trace) and the
Tempo ⇄ Loki ⇄ Prometheus drilldowns stay inside the selected environment. For
provisioned dashboards, add the variable to each JSON under
`grafana/provisioning/dashboards/json/` and template the existing queries.

### Alerting with `env`

`prometheus/rules/alerts.yml` rules should copy `env` into the alert labels
(`labels: { env: "{{ $labels.env }}" }`) and Alertmanager should route on it —
`env="prod"` → PagerDuty/critical, `env="dev"` → a muted Slack channel — so a dev
outage never pages the prod on-call.

### Trade-offs — when to split

Single stack + tag is right for now, but be aware:

- **No hard isolation.** A misbehaving dev app shares ingestion, TSDB cardinality
  and query capacity with prod.
- **Retention is global.** Loki 14 d / Tempo 7 d apply to every env; you cannot
  keep prod longer without per-tenant overrides.
- **Access control is coarse.** Anyone with Grafana sees every environment.
- **A dropped `env` tag silently pollutes** the "All" view.

Migration path: enable **Loki/Tempo multi-tenancy** (`X-Scope-OrgID: <env>` set by
Alloy per environment, one Grafana data source per tenant) before going all the
way to separate stacks.

---

## Data flow by signal

**Metrics**
```
app OTel SDK ─OTLP─► Alloy (otelcol.receiver.otlp → memory_limiter → exporter.prometheus)
                       └─► prometheus.remote_write ─► Prometheus TSDB (local)
infra exporters ─────► Prometheus scrape (node-exporter, cAdvisor local+fleet, blackbox, pushgateway, self)
spans ──────────────► Alloy spanmetrics "red" ─► remote_write ─► Prometheus  (RED: rate/errors/duration)
Tempo metrics-gen ──► remote_write ─► Prometheus  (service-graph + TraceQL local-blocks)
Grafana ◄──────────── Prometheus datasource (default; exemplars link to Tempo)
```

**Logs**
```
app OTel SDK ─OTLP─► Alloy (receiver.otlp → memory_limiter → transform "pii") ─OTLP HTTP─► Loki /otlp ─► S3
docker stdout ─────► Alloy (discovery.docker → loki.source.docker → loki.process, static env label)
                       └─► loki.write ─► Loki /loki/api/v1/push ─► S3
Grafana ◄──────────── Loki datasource (derived field trace_id → Tempo)
```

**Traces**
```
app OTel SDK ─OTLP─► Alloy (receiver.otlp → memory_limiter → transform "pii" → transform "route_template")
                       ├─► spanmetrics "red" ─► Prometheus            (all spans, pre-sampling)
                       └─► tail_sampling (100% err / 100% >1s / 10%) ─► batch ─► otelcol.exporter.otlp ─► Tempo ─► S3
Tempo ─────────────► metrics-generator ─► Prometheus  (service graph, TraceQL metrics)
Grafana ◄──────────── Tempo datasource (tracesToLogs → Loki, tracesToMetrics → Prometheus, service map)
```

---

## Run

```bash
cp .env.example .env        # fill in the scoped IAM key (valura-observability-s3)
docker compose up -d
```

Grafana: http://localhost:3000  (admin / admin123)

`.env` holds credentials for the scoped IAM user `valura-observability-s3`
(`s3:PutObject/GetObject/DeleteObject/ListBucket` on `valura-tempo-traces` +
`valura-loki-logs` only), consumed by the `loki` and `tempo` containers. It is
gitignored — never commit real keys.

---

## Instrumenting an application

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://<alloy-host>:4317
OTEL_SERVICE_NAME=my-service
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=prod,service.version=1.4.2
#                        ^ scopes every signal to an env   ^ spanmetrics dimension / deploy marker
```

`deployment.environment` is mandatory — without it the app's telemetry lands in
the "unknown" env bucket and disappears from every scoped dashboard.

### PII redaction (IFSCA / GIFT City)

`alloy/config.alloy` → `otelcol.processor.transform "pii"` drops sensitive
attribute keys (`Authorization`, `Cookie`, `*token*`, `*secret*`,
`account_number`, `broker_token`, `pan`, `aadhaar`, `passport`, …) and masks
PII-shaped values (PAN, Aadhaar, passport, email, phone, JWT) in
span/resource/log attributes **and** the log body. Verified: a span carrying
`user.pan=ABCDE1234F` and `note="client PAN ZZZZZ9999Z"` stores neither.

---

## Onboarding a new box

```bash
SSH_USER=ubuntu ./scripts/cadvisor-rollout.sh 10.200.2.60   # one cAdvisor per box on :8085
```

Then add the target to the `cadvisor-fleet` job in `prometheus/prometheus.yml`
**with its `env` label**, `promtool check config`, and reload Prometheus
(`curl -X POST localhost:9090/-/reload`). Dashboards 17346 and 19792 auto-provision.

---

## Blackbox / SLOs

`blackbox-exporter` probes the public endpoints listed in `blackbox/targets.json`
(populate from the Kuma inventory). The `blackbox` job in `prometheus/prometheus.yml`
turns each probe into `probe_success` / `probe_duration_seconds` — the error-budget
source. Give every target group an `env` label so SLOs are per-environment.

---

## Retention

Configured in `loki/loki.yml` (`limits_config.retention_period`, default 336 h) and
`tempo/tempo.yml` (`compactor.compaction.block_retention`, default 168 h). S3
lifecycle rules on both buckets expire objects a few days later as a hard backstop.
Retention is **global across all envs** — raising it for prod also raises it for dev.

---

## Optional

`alertmanager/` ships configured but commented out in `docker-compose.yml` — enable
it once there is a real receiver. `blackbox-exporter` is enabled but inert until
`blackbox/targets.json` has real endpoints.
