# resources - what to read / watch to actually understand this

Curated, not exhaustive. Ordered roughly beginner -> deep. Everything here is
free unless marked (book).

---

## Foundations (concepts, vendor-neutral)

- **Google SRE Book - Ch. 6 "Monitoring Distributed Systems"** and the
  **"Four Golden Signals"** (latency, traffic, errors, saturation).
  https://sre.google/sre-book/monitoring-distributed-systems/
- **Google SRE Workbook - Ch. 4 & 5 (SLOs, alerting on SLOs)**.
  https://sre.google/workbook/alerting-on-slos/
- **RED method** (Rate, Errors, Duration) - Tom Wilkie.
  https://grafana.com/blog/2018/08/02/the-red-method-how-to-instrument-your-services/
- **USE method** (Utilization, Saturation, Errors) - Brendan Gregg, for
  resources/hosts. https://www.brendangregg.com/usemethod.html
- **"Observability Engineering"** (book, Majors/Fong-Jones/Miranda, O'Reilly) -
  the "why", especially for traces & high-cardinality thinking.
- **"Distributed Systems Observability"** (short free O'Reilly report, Cindy
  Sridharan). https://www.oreilly.com/library/view/distributed-systems-observability/9781492033431/
- Cindy Sridharan - **"Monitoring in the time of Cloud Native"** blog post.

## Prometheus & metrics

- **Official docs - "Getting Started" + "Querying basics/examples"**.
  https://prometheus.io/docs/prometheus/latest/getting_started/
  https://prometheus.io/docs/prometheus/latest/querying/basics/
- **"Prometheus: Up & Running", 2nd ed.** (book, Julien Pivotto & Brian Brazil,
  O'Reilly) - the definitive text. Read ch. on data model, PromQL, exporters,
  alerting.
- **Brian Brazil's blog "Robust Perception"** - hundreds of short posts; start
  with "How does a Prometheus X work?" series and "Common query patterns".
  https://www.robustperception.io/blog
- **PromQL cheat sheet / "PromLabs PromQL for beginners"** (free course).
  https://promlabs.com/promql-cheat-sheet/  |  https://training.promlabs.com/
- **node_exporter collectors reference** (what each `--collector.*` does).
  https://github.com/prometheus/node_exporter
- **cAdvisor metrics reference**.
  https://github.com/google/cadvisor/blob/master/docs/storage/prometheus.md
- **Pushgateway - "when (not) to use it"** (README + this post).
  https://prometheus.io/docs/practices/pushing/
- **Alerting rules best practices**.
  https://prometheus.io/docs/practices/alerting/
- **Awesome Prometheus alerts** - copy-paste rule library (node, cadvisor,
  loki, blackbox, ...). https://samber.github.io/awesome-prometheus-alerts/

## Grafana & Alertmanager

- **Grafana fundamentals tutorial** (official, hands-on).
  https://grafana.com/tutorials/grafana-fundamentals/
- **Grafana - provisioning docs** (datasources & dashboards as code).
  https://grafana.com/docs/grafana/latest/administration/provisioning/
- **Grafana Play** - live sandbox with real dashboards to dissect.
  https://play.grafana.org/
- **Alertmanager docs - "Configuration" & "Routing tree editor"**.
  https://prometheus.io/docs/alerting/latest/configuration/
  https://prometheus.io/webtools/alerting/routing-tree-editor/  (paste your
  `route:` block, visualise it)
- **Grafana blog - "Intro to exemplars"** (metric -> trace jump).
  https://grafana.com/docs/grafana/latest/fundamentals/exemplars/

## Logs / Loki / Alloy

- **Loki docs - "Fundamentals / Overview" + "LogQL"**.
  https://grafana.com/docs/loki/latest/get-started/
  https://grafana.com/docs/loki/latest/query/
- **"Loki: like Prometheus, but for logs"** - the original design talk
  (Tom Wilkie, KubeCon) - explains why the index is small.
- **Grafana blog - "The concise guide to labels in Loki"** (cardinality).
  https://grafana.com/blog/2023/12/11/the-concise-guide-to-labels-in-loki/
- **Grafana Alloy docs - "Concepts: components" + the `loki.*` / `otelcol.*`
  reference**.
  https://grafana.com/docs/alloy/latest/
- **Migrating Promtail -> Alloy** (if you find old Promtail configs online).
  https://grafana.com/docs/alloy/latest/tasks/migrate/from-promtail/

## Traces / OpenTelemetry / Jaeger

- **OpenTelemetry docs - "Observability primer" + "Concepts / Signals"**.
  https://opentelemetry.io/docs/concepts/observability-primer/
  https://opentelemetry.io/docs/concepts/signals/traces/
- **OpenTelemetry Collector docs - "Configuration"** (receivers/processors/
  connectors/exporters/pipelines - exactly our `config.yaml`).
  https://opentelemetry.io/docs/collector/configuration/
- **otelcol-contrib component list** (every receiver/exporter you can add).
  https://github.com/open-telemetry/opentelemetry-collector-contrib
- **W3C Trace Context** (the `traceparent` header).
  https://www.w3.org/TR/trace-context/
- **Sampling** - OTel "Sampling" doc + Grafana/Honeycomb posts on head vs tail.
  https://opentelemetry.io/docs/concepts/sampling/
- **spanmetrics connector README** (how RED metrics are generated).
  https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/connector/spanmetricsconnector
- **Jaeger docs - "Architecture" + "Deployment" + "SPM / Monitor tab"**.
  https://www.jaegertracing.io/docs/latest/architecture/
  https://www.jaegertracing.io/docs/latest/spm/
- **"Mastering Distributed Tracing"** (book, Yuri Shkuro - the creator of
  Jaeger) - deep and still the best trace-specific book.
- **OpenTelemetry language SDK guides** (auto-instrumentation per language).
  https://opentelemetry.io/docs/languages/

## Proxmox / LXC

- **prometheus-pve-exporter**. https://github.com/prometheus-pve/prometheus-pve-exporter
- **node_exporter in LXC - lxcfs / cgroup caveats**: search
  "node_exporter unprivileged LXC lxcfs" (Proxmox forum threads are the best
  source; there's no single canonical doc).
- **Proxmox VE admin guide - "Monitoring" & "External Metric Server"**
  (Proxmox can also push to InfluxDB/Graphite natively).
  https://pve.proxmox.com/pve-docs/pve-admin-guide.html

## AWS / ECS

- **yet-another-cloudwatch-exporter (YACE)**.
  https://github.com/nerdswords/yet-another-cloudwatch-exporter
- **AWS - "Amazon ECS CloudWatch metrics" + "Container Insights metrics"**.
  https://docs.aws.amazon.com/AmazonECS/latest/developerguide/cloudwatch-metrics.html
  https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/Container-Insights-metrics-ECS.html
- **AWS Distro for OpenTelemetry (ADOT) - ECS docs**.
  https://aws-otel.github.io/docs/setup/ecs
- **prometheus-ecs-discovery**.
  https://github.com/teralytics/prometheus-ecs-discovery

## Hands-on playgrounds

- **"OpenTelemetry Demo"** - a full microservices app pre-instrumented, ships
  with Prometheus + Jaeger + Grafana. Run it, break it, read the traces.
  https://github.com/open-telemetry/opentelemetry-demo
- **Grafana "Intro to MLT" / killercoda scenarios** (Metrics-Logs-Traces).
  https://killercoda.com/grafana-labs
- **PromLabs "PromQL playground"** - live PromQL against sample data.
  https://demo.promlabs.com/

## Newsletters / ongoing

- **"The Observability 101" / Grafana blog** - https://grafana.com/blog/
- **CNCF TAG Observability** - whitepapers & landscape.
  https://github.com/cncf/tag-observability
- **r/PrometheusMonitoring**, **CNCF Slack #opentelemetry**, **Grafana
  community forums** - for "why is my thing not working".

---

### A realistic 2-week self-study plan

| Days | Do | Read alongside |
|---|---|---|
| 1-2 | `make up`, get all Prometheus targets green, learn 10 PromQL queries | `00`, `01`; Prometheus getting-started; PromQL cheat sheet |
| 3-4 | Grafana: datasource, import 1860 & 19792, build a panel, one alert -> webhook | `04`; Grafana fundamentals tutorial; Four Golden Signals |
| 5-6 | Loki: container logs in Explore, 10 LogQL queries, a logs panel | `02`; Loki get-started; labels-in-Loki post |
| 7-8 | Run the OpenTelemetry Demo OR instrument the repo's `test-code` app; watch a trace in Jaeger | `03`, `07`; OTel primer; Collector config doc |
| 9-10 | Correlation: exemplar metric->trace, log->trace, trace->logs; service map | `03`, `04`; exemplars doc |
| 11-12 | Your real infra: node-exporter in an LXC, pve-exporter, or ECS via YACE | `05` or `06` |
| 13-14 | Alerting for real: SLO thinking, routing tree, inhibition, silences; the runbook | `08`; SRE Workbook alerting-on-SLOs; Awesome Prometheus alerts |
