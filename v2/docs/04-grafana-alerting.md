# 04 - Grafana + Alertmanager

## Grafana's job

One UI over all three datasources. It **queries**, it does not store. Everything
here is **provisioned as code** so a fresh `docker compose up` gives you a
working Grafana with no clicking.

- `grafana/provisioning/datasources/datasources.yml` - the three datasources +
  their correlation wiring. `deleteDatasources:` at the top means "re-apply
  cleanly every restart", so editing this file + restarting Grafana is safe.
- `grafana/provisioning/dashboards/dashboards.yml` - tells Grafana to load every
  `*.json` under `dashboards/json/` and re-check every 30s.
- `grafana/provisioning/dashboards/json/stack-health.json` - a hand-written
  dashboard so you have something real on first boot.

Login: `admin` / `admin` (change via `.env` -> `GRAFANA_ADMIN_PASSWORD`).

## Datasources & correlation

| Datasource | URL | Special config |
|---|---|---|
| Prometheus (default) | `http://prometheus:9090` | `exemplarTraceIdDestinations` -> click exemplar, open trace in Jaeger |
| Loki | `http://loki:3100` | `derivedFields` regex -> "View trace in Jaeger" button on matching log lines |
| Jaeger | `http://jaeger:16686` | `tracesToLogsV2` (-> Loki), `tracesToMetrics` (-> Prometheus RED), `serviceMap`, `nodeGraph` |

`$${...}` in the YAML is an escaped `${...}` - it must reach Grafana literally
(it's a Grafana interpolation token), not be eaten by docker-compose env
substitution.

## Explore vs Dashboards

- **Explore** (compass icon): ad-hoc, one datasource, for investigating *now*.
  Split view (Cmd/Ctrl+click) to put metrics and logs side by side.
- **Dashboards**: curated panels you look at repeatedly. Import community ones by
  ID: **Dashboards -> New -> Import**.
  - `1860` Node Exporter Full
  - `19792` cAdvisor
  - `13639` Loki logs / ingestion
  - `15983` OpenTelemetry Collector
  Or run `./scripts/fetch-dashboards.sh` to drop them into provisioning.

## Template variables (dashboard dropdowns)

Add a variable (dashboard settings -> Variables):

- `box`: type *Query*, datasource Prometheus, query
  `label_values(node_uname_info, box)` -> dropdown of every box.
- `env`: `label_values(env)` once your targets/apps set an `env` label.

Then panels filter with it: `rate(container_cpu_usage_seconds_total{box=~"$box"}[5m])`.
This is how one dashboard serves every host/environment instead of one per box.

## Grafana alerting vs Prometheus alerting

**Two independent alerting systems exist. This stack uses the Prometheus one.**

- **Prometheus alerting** (what we use): rules in `prometheus/rules/*.yml`,
  evaluated by Prometheus, fired alerts sent to **Alertmanager**, which routes
  them. Rules live with your infra-as-code, work even if Grafana is down.
- **Grafana-managed alerting**: rules defined in the Grafana UI/provisioning,
  evaluated by Grafana, can span datasources (e.g. alert on a Loki query). Uses
  Grafana's own notification system (or can forward to Alertmanager).

Keep it to one to stay sane. We use Prometheus + Alertmanager. The Prometheus
datasource has `manageAlerts: true` so Grafana still *shows* those alerts on
panels and in its Alerting UI (read-only view of Prometheus/AM state).

## Alertmanager: what it does

Prometheus decides *what* is wrong. Alertmanager decides *who hears about it and
how*. `alertmanager/alertmanager.yml`:

### 1. The route tree

A tree matched top-down on alert **labels**. First matching leaf wins (unless
`continue: true`). Our tree:

```
route (receiver: default, group_by [alertname, box, service_name])
├─ severity="critical"      -> receiver: pager       (group_wait 10s, repeat 1h, continue)
├─ env=~"dev|staging"        -> receiver: low-priority (repeat 12h)
└─ severity="warning"        -> receiver: default
```

- **group_by**: alerts sharing these label values are bundled into ONE
  notification. `[alertname, box]` => "5 containers down on box X" is one
  message, not five.
- **group_wait**: after the first alert in a new group, wait this long for
  siblings before sending (30s).
- **group_interval**: once a group has notified, wait this long before sending an
  update for *new* alerts added to it (5m).
- **repeat_interval**: keep re-notifying an unresolved group every N (4h; 1h for
  pages).

### 2. Inhibition (suppress noise)

"If a bigger alert is firing, mute the smaller related ones." Ours:

- `TargetDown`+critical for a box mutes all warning/info alerts for the **same
  box** (`equal: [box]`). A dead box shouldn't also page you about its containers.
- Any `critical` mutes the matching `warning` for the same
  `alertname`/`box`/`service_name`.

### 3. Silences

Manual, time-boxed mutes set in the **Alertmanager UI (`:9093`)** or `amtool`.
Use during planned maintenance: silence `box="db01"` for 2h.

### 4. Receivers

Where a notification actually goes. The file ships **webhook** receivers
pointing at `host.docker.internal:9000` so the container starts cleanly - replace
with real integrations:

```yaml
receivers:
  - name: default
    slack_configs:
      - api_url: 'https://hooks.slack.com/services/XXX/YYY/ZZZ'
        channel: '#alerts'
        send_resolved: true
        title: '{{ .CommonLabels.alertname }} ({{ .CommonLabels.severity }})'
        text: >-
          {{ range .Alerts }}*{{ .Annotations.summary }}*
          {{ .Annotations.description }}
          <{{ .GeneratorURL }}|source> {{ end }}
  - name: pager
    pagerduty_configs:
      - routing_key: 'YOUR_PD_INTEGRATION_KEY'
        severity: '{{ .CommonLabels.severity }}'
```

Other built-ins: `email_configs`, `opsgenie_configs`, `webhook_configs`,
`telegram_configs`, `msteams_configs`, `discord_configs`.

## Wiring one alert end to end (do this once to understand it)

1. `prometheus/rules/infra-alerts.yml` already has `TargetDown` (`up == 0`).
2. `make validate && make reload-prometheus`.
3. Prometheus UI -> **Alerts** -> see `TargetDown` as `inactive`.
4. Stop a target: `docker stop cadvisor`. Wait ~2m (`for: 2m`).
5. Alert goes `pending` -> `firing`. Prometheus UI -> **Status ->
   Runtime & Build Info** confirms Alertmanager is discovered; **Alerts** shows
   firing.
6. Alertmanager UI (`:9093`) -> the alert appears, grouped, routed to a receiver.
7. `docker start cadvisor` -> alert resolves, `send_resolved` fires the "resolved"
   notification.

## Testing routing without firing anything

```bash
docker exec alertmanager amtool config routes test \
  --config.file=/etc/alertmanager/alertmanager.yml \
  severity=critical env=prod
# -> prints which receiver that label set would hit
```

## Common problems

| Symptom | Cause / fix |
|---|---|
| Grafana panel "datasource not found" | provisioning didn't run / wrong `uid`; check `docker logs grafana` |
| imported dashboard all "No data" | its panels reference `${DS_PROMETHEUS}`; edit datasource once + save, or use `fetch-dashboards.sh` |
| alert fires in Prometheus but no notification | `alerting.alertmanagers` target wrong, AM down, or route hits a receiver whose integration is a dead webhook |
| too many notifications | tune `group_by` / `group_interval` / `repeat_interval`; add inhibition |
| "resolved" spam | expected if alerts flap; fix the `for:` / threshold so they don't |
| Slack/PD says 4xx | bad webhook URL / routing key; `docker logs alertmanager` shows the HTTP error |
