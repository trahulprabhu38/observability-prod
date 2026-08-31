# prod-prometheus-setup

Observability stack: **metrics + logs + traces**, all viewed in Grafana.
Traces and logs are stored in **S3** (ap-south-1) so they never grow the local disk.

```
  app  ──OTLP :4317/:4318──►  alloy  ──► redact PII ──► template routes ──┐
                                                                          │
   traces ──► tail-sample (10% / 100% err / 100% >1s) ──► Tempo ──► s3://valura-tempo-traces
          └─► spanmetrics (RED + service.version)      ──► Prometheus
   metrics ─────────────────────────────────────────────► Prometheus (local, 15d / 40 GB)
   logs   ──► redact PII ───────────────────────────────► Loki  ──► s3://valura-loki-logs
   docker container stdout ──► alloy ──────────────────► Loki

  Grafana :3000  ── Prometheus / Loki / Tempo datasources, bi-directional trace⇄log⇄metric
```

## Components

| Service       | Port  | Role | Storage |
|---------------|-------|------|---------|
| grafana       | 3000  | Dashboards / Explore / Drilldown | `grafana_data` |
| prometheus    | 9090  | Metrics TSDB (remote-write + exemplars) | local, **15d or 40 GB** |
| loki          | 3100  | Logs | **S3** `valura-loki-logs`, retention 14d |
| tempo         | 3200  | Traces + service-graph generator | **S3** `valura-tempo-traces`, retention 7d |
| alloy         | 12345 | OTel Collector. **OTLP in: 4317 / 4318** | — |
| node-exporter | 9100  | Host metrics | — |
| cadvisor      | 8080  | Local container metrics | — |
| pushgateway   | 9091  | Batch-job metrics | — |

## Run

```bash
cp .env.example .env        # fill in the scoped IAM key (valura-observability-s3)
docker compose up -d
```

Grafana: http://localhost:3000  (admin / admin123)

## Instrumenting an application

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://<alloy-host>:4317
OTEL_SERVICE_NAME=my-service
OTEL_RESOURCE_ATTRIBUTES=service.version=1.4.2   # becomes a spanmetrics dimension / deploy marker
```

### PII redaction (IFSCA / GIFT City)

`alloy/config.alloy` → `otelcol.processor.transform "pii"` drops sensitive attribute keys
(`Authorization`, `Cookie`, `*token*`, `*secret*`, `account_number`, `broker_token`, `pan`,
`aadhaar`, `passport`, …) and masks PII-shaped values (PAN, Aadhaar, passport, email, phone,
JWT) in span/resource/log attributes **and** the log body. Verified: a span carrying
`user.pan=ABCDE1234F` and `note="client PAN ZZZZZ9999Z"` stores neither.

## Fleet cAdvisor

`scripts/cadvisor-rollout.sh` runs one cAdvisor per box on `:8085`; the `cadvisor-fleet`
job in `prometheus/prometheus.yml` scrapes them. Dashboards 17346 (Traefik) and 19792
(cAdvisor) auto-provision from `grafana/provisioning/dashboards/json/`.

## Optional

`alertmanager/` and `blackbox/` ship configured but commented out in `docker-compose.yml`.
