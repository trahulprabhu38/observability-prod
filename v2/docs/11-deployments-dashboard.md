# 11 - Deployments dashboard: is the last deploy actually healthy?

Coolify's UI doesn't surface a failed deploy loudly - you have to go look.
This dashboard makes that ambient: a green/red box per application, refreshed
every 2 minutes.

## What it actually measures

Coolify's REST API has **no working deployment-history endpoint** - both
`/api/v1/deployments` and `/api/v1/deployments/applications/:uuid` come back
empty (they only ever show an in-flight deployment, never past ones; this was
confirmed live, not assumed from docs). So instead of a deploy-event log,
`scripts/coolify-deploy-status.py` reports each application's **live
container status** (`running:healthy` vs `exited:unhealthy` / `restarting` /
etc.) - the closest honest proxy for "did the last deploy leave this
working". If a deploy fails, the container usually ends up stopped or
unhealthy, which shows red here.

## How it works

```
cron (every 2 min, on .52) -> coolify-deploy-status.py
    -> GET /api/v1/applications  (Coolify API, 10.200.1.2:8000)
    -> extract uuid/name/status/last_online_at/environment_id ONLY, discard rest
    -> PUT metrics to Pushgateway (localhost:9091, already scraped by Prometheus)
```

Metrics: `coolify_app_up` (1/0), `coolify_app_healthy` (1/0/-1 if no
healthcheck configured), `coolify_app_last_online_timestamp`,
`coolify_poll_success`, `coolify_poll_duration_seconds`,
`coolify_last_poll_timestamp_seconds` (watch this for staleness if the cron
stops), `coolify_poll_apps_total`.

## Why it's safe to poll this often

The `/api/v1/applications` response is ~1.9MB across 181 apps (measured) and
takes ~0.3-1.7s for Coolify to build - and it embeds **real secrets per app**
(`manual_webhook_secret_github/gitlab/bitbucket/gitea`, full
`docker_compose_raw`/`docker_compose` with env vars). The poller pulls that
whole response into memory, keeps exactly five scalar fields per app, and
never writes the rest to disk or anywhere else - the secrets never leave that
one Python process.

Project/environment name mapping (`/api/v1/projects` + one call per project,
~39 requests, no secrets, sub-KB each) is cached for an hour since that
structure barely changes - it's not re-fetched every poll.

Net load: one ~1.9MB request every 2 minutes on an internal LAN, plus an
hourly batch of ~39 tiny ones. That's negligible bandwidth; the only real
cost is ~0.3-1.7s of Coolify's own app-server CPU time per poll, which is why
this runs every 2 minutes rather than every 1.

## The token

`COOLIFY_TOKEN` lives in `v2/.env` on `.52` (gitignored, never committed) -
same pattern as `GRAFANA_ADMIN_PASSWORD`. Generated from the Coolify UI
(Settings -> Keys & Tokens), not minted programmatically - creating an API
token by scripting against Coolify's own auth database was deliberately not
done; that's a decision for whoever owns that instance, not something to
automate around.

## Folder access

`deployments` folder is **Prod-View only** (not General-View) - unlike
`infra`, this dashboard shows live production status across every client
project on the Coolify instance (`Valura`, `DSP`, `P3-2Cents`, `ICICI`, etc.),
not just the UAE/IND stack this repo otherwise tracks. Revisit if that scope
turns out to be wrong.

## Redeploying the dashboard after a generator change

```bash
python3 scripts/gen-deploy-dashboard.py grafana/provisioning/dashboards/json/deployments
```

## Known gaps

- Reports current health, not a deploy-event timeline - two deploys in a row
  that both leave the app healthy look identical here.
- No alerting wired up yet - this is a dashboard to look at, not a page.
- Apps with no healthcheck configured show `coolify_app_healthy = -1`
  ("unknown") - that's most of them; `coolify_app_up` (just "is the container
  running") is the more reliable of the two signals until more apps get
  healthchecks.
