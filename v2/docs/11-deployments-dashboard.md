# 11 - Deployments: is the last deploy actually healthy, and did it build?

Coolify's UI doesn't surface a failed deploy loudly - you have to go look.
Two dashboards make that ambient, answering two different questions:

| Dashboard | Question | Source |
|---|---|---|
| `deployments` | Is the app running *right now*? | live container status, polled from the Coolify API |
| `deployment-builds` | Did the last (up to 3) *build attempts* succeed? | Coolify's own deployment-history table, read directly |

They deliberately disagree sometimes - that's the point. A failed build
often leaves the *previous* container running, so `deployments` stays green
while `deployment-builds` shows red for the same app. `deployment-builds`
cross-references both to surface exactly that case explicitly (see below).

## Global vs. per-environment

Both dashboards actually ship as four each: one global pair in the
`deployments` folder (Prod-View only, all 181 apps across every client
project on the Coolify instance), and three scoped pairs -
`deployments-dev`/`deployment-builds-dev`,
`deployments-staging`/`deployment-builds-staging`,
`deployments-prod`/`deployment-builds-prod` - living in the `dev`/`staging`/
`prod` folders and filtered to just that environment's own projects. The
scoped ones exist so developers (General-View, no access to `prod` or the
global `deployments` folder) still get deploy-status visibility for the
environments they're actually allowed to see. See `docs/10-rbac-teams-access.md`
for the folder/permission table.

The scoping filters by Coolify **project** name, not "environment" -
Coolify's own environment field is just `production` for nearly every app
regardless of which of our three groups it's in (checked live), so it
carries no signal for this split. `gen-deploy-dashboard.py` and
`gen-build-status-dashboard.py` each have a `SCOPES` dict with the project
regex per environment; note the casing there is the real Coolify
project name from the API/DB (e.g. `Valura-development`,
`valura-UAE-staging`), which differs from the lowercase
`coolify.projectName` docker-label slug (`valura-development`) used
elsewhere in this repo for cAdvisor filtering - verified against live label
values, not assumed, after the first attempt at this used the wrong casing
and matched zero apps.

## `deployments` - what it actually measures

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

## `deployment-builds` - where the data actually lives

The API gap above is real - Coolify's API genuinely cannot tell you about
past deployments. But the data exists: Coolify records every build in its
own Postgres table, `application_deployment_queues` (6,100+ rows, since
2026-07-07 on this instance) - it's just never exposed over the API, only
rendered into the deploy-log view in the Coolify UI itself.

`scripts/coolify-build-status.py` reads that table directly with a read-only
SQL query (window-functioned to the latest 3 rows per app, joined against
`applications`/`environments`/`projects` for names) via
`docker exec coolify-db psql`. That container's Postgres port isn't published
to the host network, so **this script has to run on the Coolify box itself
(10.200.1.2)**, not on `.52` like the other poller - it pushes its results
cross-network to the same Pushgateway on `.52` instead (confirmed reachable
both directions). Cron there, every 5 minutes (build history changes far
less often than live status, hence the longer interval than `deployments`'s
2 minutes).

This is cheap: the query touches ~441 rows and takes ~0.14s locally, several
orders of magnitude lighter than the ~1.9MB API call the other poller has to
make - no API token involved at all for this one.

Metrics: `coolify_build_success` (1=finished, 0=failed, -1=other e.g.
cancelled-by-user) labelled with `rank` (1=latest, 2, 3) and
`deployment_uuid`, `coolify_build_timestamp_seconds`,
`coolify_build_duration_seconds`,
`coolify_build_poll_success`/`_duration_seconds`/`_rows_total`,
`coolify_build_logs_shipped_total`, `coolify_build_last_poll_timestamp_seconds`.

The dashboard's most useful panel cross-references the two data sources in
one query: `coolify_build_success{rank="1"} == 0 and on(uuid) coolify_app_up
== 1` - latest build failed, but the container is up anyway. That's the
exact "silent failure" scenario this was built for; 4 apps were hitting it
the day this shipped.

## Build logs

`application_deployment_queues.logs` (a JSON array of log entries) **is now
read** - for each of the last 3 builds per app, the poller ships it to Loki
as stream `{job="coolify_build_logs", project, environment, app}` with
per-line structured metadata `deployment_uuid` / `status` / `commit` /
`stream`. Build logs can contain whatever a build script echoed, so this
makes them readable by anyone with access to the dashboard's folder - that's
the deliberate trade for being able to read a failed build without opening
Coolify.

Each build's log is shipped exactly once (state file
`/root/.coolify_build_logs_pushed.json` on 10.200.1.2), oldest-first so
Loki's per-stream ordering accepts it, capped at 60 new logs per cron run
(spreads the first-run backfill over ~30 min). Loki keeps **14 days**, so a
build older than that can't be shipped - it's recorded as done so it isn't
retried, and apps that haven't deployed in ~2 weeks show "no data" in the
build-log panel. Active apps always have their logs; every new build ships
fine.

On the `deployment-builds` dashboard: pick `$app` + `$rank` (1=latest) in
the top bar, or click a tile in the "latest build" board / an app name in
either table - a hidden chained `$deployment_uuid` var
(`label_values(coolify_build_success{app="$app", rank=~"$rank"},
deployment_uuid)`) resolves it, and the "build log" Logs panel queries
`{job="coolify_build_logs", app="$app"} | deployment_uuid=~$deployment_uuid`.

## Folder access

`deployments` folder (both dashboards live here) is **Prod-View only** (not
General-View) - unlike `infra`, these show live production status across
every client project on the Coolify instance (`Valura`, `DSP`, `P3-2Cents`,
`ICICI`, etc.), not just the UAE/IND stack this repo otherwise tracks.
Revisit if that scope turns out to be wrong.

## Redeploying a dashboard after a generator change

```bash
# both take the top-level json/ dir - they each write their own global copy
# into deployments/ plus three scoped copies into dev/, staging/, prod/
python3 scripts/gen-deploy-dashboard.py grafana/provisioning/dashboards/json
python3 scripts/gen-build-status-dashboard.py grafana/provisioning/dashboards/json
```

`coolify-build-status.py` itself is deployed by hand to `/usr/local/bin/` on
10.200.1.2 (not `.52`) - a repo change to it needs re-copying there, the
usual `.52` sync flow doesn't reach that box.

## Known gaps

- `deployments` reports current health, not a deploy-event timeline - two
  deploys in a row that both leave the app healthy look identical there.
  `deployment-builds` is the one with actual build-attempt history (last 3).
- No alerting wired up yet on either - these are dashboards to look at, not
  pages.
- Apps with no healthcheck configured show `coolify_app_healthy = -1`
  ("unknown") - that's most of them; `coolify_app_up` (just "is the container
  running") is the more reliable of the two signals until more apps get
  healthchecks.
- `deployment-builds` only ever shows the last 3 attempts per app (by
  design, matching what was asked for) - there's 2 months of full history in
  `application_deployment_queues` if a longer trend view is ever wanted.
