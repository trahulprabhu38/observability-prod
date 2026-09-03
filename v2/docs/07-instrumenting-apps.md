# 07 - Instrumenting your applications

Infra metrics (node-exporter, cAdvisor) tell you a box is unhealthy. **App
instrumentation** tells you *your code* is unhealthy - which endpoint, which
query, which downstream call. This is where traces + app metrics + structured
logs come from.

## The one endpoint to remember

Everything an app emits goes to the **OpenTelemetry Collector** over OTLP:

```
OTEL_EXPORTER_OTLP_ENDPOINT=http://<observability-box>:4317   # gRPC
# or  http://<observability-box>:4318  with OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
```

From there: traces -> Jaeger, metrics -> Prometheus, logs -> Loki. The app
doesn't know or care about the backends.

## Resource attributes - set these on every service

```bash
OTEL_SERVICE_NAME=checkout-api
OTEL_RESOURCE_ATTRIBUTES=deployment.environment=prod,service.version=1.6.3,service.namespace=shop
```

- `service.name` - **the** identity. Shows up as the service in Jaeger, the
  `service_name` label on span-metrics, and (ideally) a Loki label. Pick stable,
  lowercase, hyphenated names and never reuse one.
- `deployment.environment` - `prod` / `staging` / `dev`. Scopes dashboards and
  alert routing. Without it your telemetry lands in an "unknown" bucket.
- `service.version` - enables deploy markers ("latency jumped at 14:00, right
  when v1.6.3 rolled out") and per-version RED.

## Auto-instrumentation (start here - near-zero code)

| Language | How | Covers |
|---|---|---|
| **Java** | `-javaagent:opentelemetry-javaagent.jar` | Servlet, Spring, JDBC, Kafka, gRPC, HTTP clients, logs |
| **Python** | `pip install opentelemetry-distro opentelemetry-bootstrap` then run via `opentelemetry-instrument python app.py` | Flask/Django/FastAPI, requests, psycopg, redis, celery |
| **Node.js** | `npm i @opentelemetry/auto-instrumentations-node` + `node --require @opentelemetry/auto-instrumentations-node/register app.js` | http, express/fastify/koa, pg, mysql, redis, grpc |
| **.NET** | `dotnet add package OpenTelemetry.AutoInstrumentation` + the install script | ASP.NET Core, HttpClient, EF Core, SQL |
| **Go** | no runtime agent - use SDK + `otelhttp`/`otelgin`/`otelsql` wrappers (small code change) | what you wrap; eBPF auto-instr exists but is early |

Auto-instrumentation gives you **traces** for inbound requests and outbound
calls, plus HTTP/DB **metrics**, immediately. That alone is enough to light up
Jaeger and the RED dashboards.

## Manual spans (for your own logic)

Wrap the interesting bits:

```python
from opentelemetry import trace
tracer = trace.get_tracer("checkout")

with tracer.start_as_current_span("apply_discount") as span:
    span.set_attribute("cart.item_count", len(items))
    span.set_attribute("discount.code", code)          # OK: bounded-ish
    # span.set_attribute("user.email", email)          # NO: PII + high cardinality
    result = do_work()
    span.set_attribute("discount.applied_pct", result.pct)
```

Attribute hygiene:
- Good attributes: enums, counts, booleans, IDs you'll actually search by in
  Jaeger (`order.id` is fine as a *span attribute* - it's searchable and it does
  **not** become a metric label).
- Never put PII in attributes (`transform/pii` in the collector is a backstop,
  not permission). Never put unbounded values in things that become **metric**
  dimensions.

## App metrics beyond RED

RED (rate/errors/duration per endpoint) comes free from span-metrics. For
business/domain metrics, use either:

1. **OTel metrics API** - `meter.create_counter("orders_placed_total")`, exported
   OTLP to the collector. Preferred; one SDK.
2. **Prometheus client library** - expose `/metrics`, and either let the
   collector scrape it (add a `prometheus` receiver) or, for non-container/batch
   jobs, push to **Pushgateway** (`01-metrics-prometheus.md`).

Counters for events, histograms for durations/sizes, gauges for levels. Keep
label sets tiny.

## Logs: make them structured and correlated

- Log **JSON** to stdout. One object per line. Include at least `level`, `msg`,
  `service`, and - critically - `trace_id` and `span_id` when inside a request.
- Every OTel SDK has a logging bridge/appender that injects the current
  `trace_id`/`span_id` into log records automatically - enable it. That's what
  makes "log line -> its trace" work (Loki derived field -> Jaeger).
- Don't log secrets/PII. Don't log a line per iteration of a hot loop.
- stdout is enough - Alloy tails it into Loki. Only use the OTLP log exporter if
  you want richer structured attributes.

## Batch / cron jobs

They exit before Prometheus can scrape them. Push a "last success" gauge to
Pushgateway at the end (`01-metrics-prometheus.md` has the snippet), then alert
on `time() - myjob_last_success_timestamp_seconds > <expected_interval * 1.5>`.

For traces in a batch job, the SDK still works - just call
`tracer_provider.shutdown()` (or `force_flush()`) before the process exits or
you'll lose the tail of the buffer.

## Sampling from the app side

Leave it at "always on" while volume is low. When you need to cut it:
`OTEL_TRACES_SAMPLER=parentbased_traceidratio`,
`OTEL_TRACES_SAMPLER_ARG=0.25`. Better: keep the app at 100% and do **tail
sampling in the collector** (`03-traces-otel-jaeger.md`) so you still keep all
errors.

## Checklist for a newly instrumented service

- [ ] `OTEL_SERVICE_NAME`, `deployment.environment`, `service.version` set
- [ ] OTLP endpoint reachable from the app's network to the obs box `:4317`
- [ ] a request to the app produces a trace in Jaeger within ~10s
- [ ] `traces_spanmetrics_calls_total{service_name="..."}` appears in Prometheus
- [ ] logs are JSON on stdout with `trace_id`, visible in Grafana Explore -> Loki
- [ ] clicking a log line's "View trace" opens the right trace
- [ ] no PII in span attributes (search the service in Jaeger, eyeball a few)
- [ ] proxies/LBs between services forward the `traceparent` header
