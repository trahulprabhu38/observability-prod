# 03 - Traces with OpenTelemetry + Jaeger

## What a trace is

A **trace** follows one request across every service it touches. It's a tree of
**spans**:

```
trace 7f3a...  (total 412ms)
└─ span  GET /checkout          service=web        0ms ───────────────── 412ms
   ├─ span  POST /cart/validate service=cart      12ms ──── 78ms
   ├─ span  SELECT items        service=cart-db   30ms ─ 46ms
   └─ span  POST /payments      service=payments  90ms ─────────── 400ms
      └─ span  stripe.charge    service=payments 110ms ────────── 395ms   ERROR
```

Each span has: name, service, start time, duration, status (OK/ERROR),
parent span id, **trace id** (shared by the whole tree), and **attributes**
(key/values: `http.route`, `db.statement`, `user.tier`, ...).

Traces answer "**where** did the time go / **which** call failed", which metrics
and logs can't.

## Context propagation (how spans in different services join up)

Service A makes an HTTP call to service B. A's SDK injects headers:

```
traceparent: 00-7f3a9b...-3c2f...-01
```

B's SDK reads them, so B's spans get the **same trace id** and point their
parent at A's span. This is the **W3C Trace Context** standard; every OTel SDK
does it automatically for common HTTP/gRPC/messaging libraries. Your job is
mostly: install the SDK, set 3 env vars, don't strip the `traceparent` header in
proxies.

## OTLP - the wire protocol

**OpenTelemetry Protocol**. One protocol for traces, metrics **and** logs, over
gRPC (`:4317`) or HTTP/protobuf (`:4318`). Every SDK and collector speaks it.
Your apps send OTLP to the **collector**, never straight to Jaeger (so you can
sample/redact/enrich centrally and swap the backend without touching apps).

## The pipeline: OpenTelemetry Collector

`otel-collector/config.yaml`. A collector pipeline has four component kinds:

| Kind | Role | In this config |
|---|---|---|
| **receivers** | data in | `otlp` (grpc + http) |
| **processors** | transform in flight, in order | `memory_limiter`, `resourcedetection`, `transform/pii`, `batch` |
| **connectors** | output of one pipeline = input of another | `spanmetrics` (spans -> metrics) |
| **exporters** | data out | `otlp/jaeger`, `prometheusremotewrite`, `otlphttp/loki`, `debug` |

Wired in `service.pipelines`:

```
traces:  otlp -> memory_limiter -> resourcedetection -> transform/pii -> batch
                 -> [ otlp/jaeger , spanmetrics , debug ]

metrics: [ otlp , spanmetrics ] -> memory_limiter -> batch -> prometheusremotewrite

logs:    otlp -> memory_limiter -> transform/pii -> batch -> otlphttp/loki
```

Component notes:

- **memory_limiter** - checks RAM every 1s; starts refusing data at 80% so the
  collector never OOMs the box. Always first.
- **resourcedetection** - stamps `host.name`, `os.type`, and anything from `env`
  onto every span/metric/log.
- **transform/pii** - OTTL statements that delete secret-ish attribute keys and
  mask emails. This is your **one enforced redaction point** - extend it rather
  than trusting every app. (The v1 stack has a much fuller GIFT-City/IFSCA
  ruleset in `../../prod-prometheus-setup/alloy/config.alloy` you can lift.)
- **batch** - groups spans for compression/throughput. Always last.
- **spanmetrics connector** - see next section.
- **debug exporter** - prints a one-line summary of every batch to
  `docker logs otel-collector`. Set `verbosity: detailed` to dump full payloads
  while debugging, then turn it back to `basic`.

### Live debugging

`http://localhost:55679/debug/tracez` (zpages) shows recent/slow/errored spans
the collector has seen. `http://localhost:13133` is the health check. The
collector's own metrics are on `:8888` and Prometheus scrapes them
(`otelcol_receiver_accepted_spans`, `otelcol_exporter_send_failed_spans`, ...).

## Span-metrics = the RED method, for free

The **spanmetrics connector** watches every span and emits metrics:

- `traces_spanmetrics_calls_total{service_name, span_name, status_code, ...}`
  -> **R**ate and **E**rrors
- `traces_spanmetrics_duration_milliseconds_bucket{...}` (a histogram)
  -> **D**uration (percentiles via `histogram_quantile`)

`namespace: traces.spanmetrics` in the config is why the metric names come out
`traces_spanmetrics_*`. `dimensions:` adds extra labels (`http.route`,
`http.response.status_code`, `service.version`). `exemplars.enabled: true`
attaches a sample `trace_id` to data points so Grafana can jump metric -> trace.

These metrics flow into the `metrics` pipeline -> remote-write -> Prometheus.
The recording rules in `prometheus/rules/stack-alerts.yml` roll them into
`service:request_rate:5m`, `service:error_rate:5m`, `service:latency_p95_ms:5m`.
**RED runs on 100% of spans, before any sampling**, so rates stay correct even
if you only store 10% of traces.

## Sampling: head vs tail

Storing every span is expensive at volume. Two strategies:

- **Head sampling** (in the SDK): decide at the *start* of the trace, e.g. keep
  10%. Cheap, simple, but you'll miss 90% of your errors.
  Set `OTEL_TRACES_SAMPLER=parentbased_traceidratio` +
  `OTEL_TRACES_SAMPLER_ARG=0.1`.
- **Tail sampling** (in the collector): buffer whole traces for a few seconds,
  then decide with full knowledge - **keep 100% of errors, 100% of slow traces,
  10% of the boring ones**. This is the good one. The config block is at the
  bottom of `otel-collector/config.yaml`, commented out. To enable: define a
  `tail_sampling` processor, remove `batch` from the traces pipeline (tail
  sampling must see the whole trace un-batched), and put `tail_sampling` last.

For a learning setup, **start with no sampling** (store everything, low volume),
add tail sampling when trace storage grows.

## Jaeger

`jaegertracing/all-in-one` = collector + query + UI in one container.

- Receives OTLP on its own `:4317/:4318` (`COLLECTOR_OTLP_ENABLED=true`). Our
  collector's `otlp/jaeger` exporter targets `jaeger:4317` inside the network;
  those ports are published as `14317/14318` on the host for direct testing.
- **Storage**: `badger` - an embedded key-value store on the `jaeger_data`
  volume. Survives restarts. Good to a few million spans; for real volume move to
  Elasticsearch/Cassandra or switch to Jaeger v2 + a real backend.
- **UI** on `:16686`: search by service / operation / tags / duration / trace id.
  The **System Architecture** tab draws a service dependency graph.
- **Monitor tab (SPM)**: RED metrics per service, read from Prometheus. Enabled
  via `METRICS_STORAGE_TYPE=prometheus` + `PROMETHEUS_SERVER_URL`. It expects the
  span-metrics naming from the OTel spanmetrics connector - the
  `PROMETHEUS_QUERY_*` env vars in the compose file tune that matching. If the
  Monitor tab is empty, it's almost always a metric-name mismatch; the traces
  themselves are unaffected. (Details:
  `https://www.jaegertracing.io/docs/latest/spm/`.)

### Jaeger v1 vs v2

v1 (`all-in-one:1.65.0`, used here) is simple and stable. **Jaeger v2** is built
*on* the OpenTelemetry Collector - its config file is literally a collector
config. When you outgrow badger, migrating to v2 + Elasticsearch is the path, and
your mental model already transfers because you learned the collector here.

## Correlation in Grafana

Configured in `grafana/provisioning/datasources/datasources.yml`:

| From | To | Mechanism |
|---|---|---|
| metric point | trace | Prometheus **exemplar** carries `trace_id`; "View trace in Jaeger" |
| log line | trace | Loki **derived field** regex extracts `trace_id` |
| span | logs | Jaeger datasource `tracesToLogsV2` -> Loki, time-boxed ±5m, filtered by trace id |
| span | metrics | `tracesToMetrics` -> Prometheus RED queries |
| trace | service map | `serviceMap` + `nodeGraph` off span-metrics |

Try it: open a latency panel, turn on exemplars, click a diamond -> Jaeger opens
that exact trace -> click a span -> "Logs for this span" -> Loki.

## Instrumenting an app (short version)

```bash
OTEL_EXPORTER_OTLP_ENDPOINT=http://<obs-box>:4317
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=checkout-api
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=prod,service.version=1.4.2
```

Full per-language guide: `07-instrumenting-apps.md`.

## Common problems

| Symptom | Cause / fix |
|---|---|
| no traces in Jaeger | app not exporting (check its OTLP endpoint/protocol), or collector -> jaeger export failing (`otelcol_exporter_send_failed_spans_total`) |
| traces from service A but not B | `traceparent` header stripped by a proxy/load balancer between them |
| broken trace tree (spans not linked) | mixed propagation formats; force W3C `tracecontext` everywhere |
| Monitor tab empty in Jaeger | span-metric name mismatch - traces still fine; see SPM notes above |
| collector "refused" spans | `memory_limiter` tripped - give the container more RAM or reduce volume |
| cardinality warning on span-metrics | a high-cardinality attribute is a `dimension` (e.g. raw `url.path`) - use `http.route` / templated paths |
| exemplars not showing | Prometheus needs `--enable-feature=exemplar-storage` (set) and the panel must have "Exemplars" toggled on |
