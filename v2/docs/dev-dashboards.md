# dev-UAE / dev-IND dashboards

Two Grafana dashboards for the shared Coolify dev box (`10.200.2.51`), one per
region. Provisioned from
`v2/grafana/provisioning/dashboards/json/dev-{uae,ind}.json`.

| Dashboard | uid | Coolify project it filters on |
|---|---|---|
| **dev-UAE** | `dev-uae` | `valura-development` |
| **dev-IND** | `dev-ind` | `global-valura-dev` |

They are byte-for-byte identical apart from that project constant. Structure:

| Section | Source | Notes |
|---|---|---|
| summary (stat row) | Prom + Loki | running containers, restarts/1h, CPU cores, memory, log & error rate |
| containers – CPU / memory / network | cAdvisor (`box="valura-dev"`, `container_label_coolify_projectName=<project>`) | grouped by `container_label_coolify_resourceName`; `$resource` multi-select var |
| restarts & uptime | cAdvisor | `changes(container_start_time_seconds[1h])`, uptime table |
| dev host (10.200.2.51) | node-exporter (`job="node-fleet"`, `box="valura-dev"`) | **shared** – the box hosts both regions, so these panels are the same on both dashboards |
| logs (Loki) | `{coolify_project=<project>, host="dev-server-1"}` | volume by level, rate by service, error/warn stream, live tail filtered by `$resource` |
| traces (Jaeger + RED) | Jaeger `$service`, `traces_spanmetrics_*` | **empty until apps emit spans** – see below |

## Template variables

- `project` – constant, hidden (the region's Coolify project)
- `resource` – `label_values(container_last_seen{container_label_coolify_projectName="<project>", box="valura-dev"}, container_label_coolify_resourceName)`, multi, includes All
- `service` – `label_values(traces_spanmetrics_calls_total, service_name)` (populates once traces flow)

## Turning on traces

The pipeline is live and smoke-tested
(`app → Alloy :4318 (.51) → OTel Collector (.52) → Jaeger`), but no Valura dev
app emits spans yet. Per Coolify service, add these env vars and redeploy:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://10.200.2.51:4318
OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=none
OTEL_LOGS_EXPORTER=none
OTEL_SERVICE_NAME=<resource name, e.g. valura-api-dev>
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=dev,region=<uae|ind>
```

Then per stack:

| Stack | How |
|---|---|
| Node.js | `npm i @opentelemetry/auto-instrumentations-node` and start with `--require @opentelemetry/auto-instrumentations-node/register`, or add `NODE_OPTIONS=--require @opentelemetry/auto-instrumentations-node/register` |
| Python | `pip install opentelemetry-distro opentelemetry-exporter-otlp && opentelemetry-bootstrap -a install`, run under `opentelemetry-instrument` |
| Go | manual – `go.opentelemetry.io/otel` + `otelhttp`/`otelgin` middleware |

RED metrics (`traces_spanmetrics_calls_total`, `_latency_bucket`) are produced
automatically by the collector's `spanmetrics` connector once spans arrive; the
"traces" row panels start filling with no further config.

## What still needs doing

- **Alertmanager**: v2 ships route-tree + rules but receivers are webhook
  placeholders – wire a real Slack/email receiver.
- **Jaeger storage is in-memory** (dodged a badger-perms + a Jaeger-1.65
  metrics-registration bug on this host). Traces are lost on `jaeger` restart.
  Move to Jaeger v2 / a persistent backend when traces matter.
- **blackbox-exporter** from the old prod stack isn't in v2 yet – re-add if you
  want the 63-endpoint SLO probing back.
- **dubai cAdvisor** (`86.106.26.45:8085`) target is down – was down in the old
  stack too; unreachable from `.52`.
