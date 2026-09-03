# 02 - Logs with Loki + Alloy

## The core idea: Loki indexes labels, not text

Elasticsearch builds a full-text inverted index of every word in every log line -
powerful, expensive, operationally heavy. **Loki does not.** Loki:

1. Groups incoming lines into **streams**, identified by a small **label set**
   (`{job="docker", container="api", box="observability", level="error"}`).
2. Appends each stream's lines into a compressed **chunk** on disk (or S3).
3. Indexes **only the labels + time range** of each chunk (the TSDB index).

A query like `{container="api"} |= "timeout"`:
- uses the index to find the handful of chunks for that stream in the time range,
- decompresses them and **greps** for `timeout`.

Consequence: **cheap to run, but label cardinality is everything.**

## The cardinality rule (again, because it kills Loki setups)

- A **label** value must be low-cardinality: `job`, `container`, `level`, `env`,
  `box`. Something you'd put on a dashboard dropdown.
- **Never** make a label out of: `trace_id`, `request_id`, `user_id`, `path`,
  `pod` hash, timestamps, `ip`. Each new value = a new stream = a new set of
  chunks and index entries. Thousands of streams = slow writes, slow queries,
  OOM.
- High-cardinality fields go **in the log line** (ideally as JSON) and you filter
  them at query time: `| json | user_id="123"`.
- Loki 3.x has **structured metadata** (`allow_structured_metadata: true` in
  `loki/loki.yml`) - a place to attach `trace_id` etc. to a line *without* it
  becoming a stream label. OTLP log attributes land here.

## What ships logs here: Alloy

`alloy/config.alloy`. In this stack Alloy has exactly one job: **tail every
Docker container's stdout/stderr on this host and push to Loki.**

Pipeline, component by component (Alloy config is a graph; `forward_to` wires
outputs to inputs):

```
discovery.docker      -> list running containers (via /var/run/docker.sock), refresh 5s
discovery.relabel     -> turn docker metadata into labels (container=, compose_project=)
                         and DROP alloy's own container (no feedback loop)
loki.source.docker    -> actually stream the logs
loki.process "enrich" -> stage.static_labels {job="docker", box="observability"}
                         stage.json  -> parse JSON lines, pull out level + trace_id
                         stage.labels -> promote ONLY `level` to a real label
                         stage.replace -> normalise "warning" -> "warn"
loki.write "default"  -> POST http://loki:3100/loki/api/v1/push
```

Why Alloy and not Promtail: Promtail is EOL (Feb 2025 LTS end). Alloy is its
successor and is a full **OpenTelemetry Collector distribution** - the same
`otelcol.*` components you'll meet in `03-traces-otel-jaeger.md` exist here too.

### App OTLP logs take a different path

Structured logs emitted by an app's OpenTelemetry SDK go to the **otel-collector**
(`:4317/:4318`), which forwards them to Loki's native OTLP endpoint
(`http://loki:3100/otlp`). Resource attributes (`service.name`,
`deployment.environment`) become stream labels or structured metadata. So:

- container stdout ............ Alloy -> Loki `/loki/api/v1/push`
- app OTLP logs ............... otel-collector -> Loki `/otlp`

Both end up queryable the same way in Grafana.

## LogQL - the query language

LogQL = "PromQL for logs". Two halves: a **stream selector** `{}` (uses the
index, always required) then optional **line filters** and **parsers** (`|`).

```logql
# all lines from the api container
{container="api"}

# ... containing "timeout" (case-insensitive regex match)
{container="api"} |~ "(?i)timeout"

# ... excluding health checks
{container="api"} != "/healthz"

# parse JSON, filter on a field, show only two fields
{container="api"} | json | status_code>=500 | line_format "{{.method}} {{.path}} {{.msg}}"

# parse logfmt
{job="docker"} | logfmt | level="error"

# extract with a regex into a label
{container="nginx"} | regexp `(?P<status>\d{3}) (?P<bytes>\d+)` | status="502"

# METRIC query: error lines per second per container (turns logs into a graph)
sum by (container) (rate({job="docker"} |~ "(?i)error" [5m]))

# count by a parsed field
sum by (level) (count_over_time({job="docker"} | json | __error__="" [5m]))
```

Filter order matters for speed: **most selective label selector first**, then
cheap line filters (`|=`, `!=`), then expensive ones (`|~`, `| json`).

## In Grafana

- **Explore -> Loki**: pick labels from the dropdown, or type LogQL. The "Logs
  volume" bar at the top is powered by `volume_enabled: true` in the config.
- **Live tail**: the "Live" button streams new lines.
- **Trace correlation**: the Loki datasource has a **derived field** (see
  `grafana/provisioning/datasources/datasources.yml`) - a regex that pulls a
  `trace_id` out of the line and renders a "View trace in Jaeger" button.
  So: log line -> its trace, one click.
- Add a **Logs panel** to a dashboard with a query like
  `{box="$box"} |~ "(?i)(error|panic)"` (there's one on the provisioned
  "Stack Health" dashboard).

## Retention & storage

- `loki/loki.yml` -> `limits_config.retention_period: 336h` (14d). The
  **compactor** enforces it (`retention_enabled: true`) - it rewrites index
  files and deletes chunks past the cutoff on a 10m loop.
- Storage here is the **local filesystem** (`loki_data` volume), single-binary
  mode. Simple, survives restarts, fine to tens of GB/day on one box.
- **Moving to object storage later**: replace the `storage_config` /
  `common.storage` blocks with an `aws:` (S3), `gcs:`, or `azure:` section and
  add a second `schema_config` entry dated at the cutover. The v1 stack in
  `../../prod-prometheus-setup/loki/loki.yml` is a working S3 example.

## Alloy operations

```bash
make reload-alloy         # POST /-/reload, no restart
open http://localhost:12345   # live pipeline graph; click a node to see throughput
```

The Alloy UI shows each component's health and, with `livedebugging` (add
`livedebugging { enabled = true }`), the actual data flowing through.

## Common problems

| Symptom | Cause / fix |
|---|---|
| no logs in Grafana at all | Alloy can't read `/var/run/docker.sock` (perms), or can't reach `loki:3100` |
| `429` / "ingestion rate limit exceeded" in Alloy logs | raise `ingestion_rate_mb` / `ingestion_burst_size_mb` in `loki/loki.yml`, or you're logging too much |
| `too many outstanding requests` | query too broad; add a tighter label selector / shorter time range |
| Loki RAM/disk blowing up | stream explosion - you promoted a high-cardinality field to a label. Check `loki_ingester_memory_streams`. Remove the label. |
| `entry out of order` | a container's clock is skewed, or two shippers sending the same stream |
| JSON fields not parsed | line isn't valid JSON, or you forgot `| json`; check `__error__` |
| level label missing | the app doesn't log `level` in JSON; adjust the `stage.json` expressions or `stage.regex` |
