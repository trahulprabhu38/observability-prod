#!/usr/bin/env python3
"""deployment-builds dashboard - did the last (up to) 3 *builds* of each
Coolify app succeed, independent of whether the app happens to be running
right now.

Complements deployments.json: that one shows current container health
(coolify_app_up from coolify-deploy-status.py). This one shows build outcome
(coolify_build_success from coolify-build-status.py, read straight out of
Coolify's own deployment-history table - see that script's docstring for why
the API can't give us this). The two are deliberately cross-referenced here:
a build can fail while the app keeps running on its last-good container,
which is exactly the silent-failure case this was built for.
"""
import json, sys

PROM = {"type": "prometheus", "uid": "prometheus"}

_id = [0]
def nid():
    _id[0] += 1
    return _id[0]

def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}

def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False,
            "gridPos": g(0, y, 24, 1), "panels": []}

def text_panel(gp, md):
    return {"id": nid(), "type": "text", "gridPos": gp,
            "options": {"mode": "markdown", "content": md}}

def stat(title, gp, expr, unit="short", thresholds=None, decimals=None, graph="none", mappings=None):
    defaults = {"unit": unit, "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": thresholds or [{"color": "text", "value": None}]}}
    if decimals is not None: defaults["decimals"] = decimals
    if mappings: defaults["mappings"] = mappings
    return {
        "id": nid(), "type": "stat", "title": title, "datasource": PROM, "gridPos": gp,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "auto", "textMode": "auto", "colorMode": "value",
                    "graphMode": graph, "justifyMode": "auto"},
        "targets": [{"refId": "A", "datasource": PROM, "expr": expr, "instant": True}],
    }

def status_board(title, gp, expr, desc=""):
    return {
        "id": nid(), "type": "stat", "title": title, "datasource": PROM, "gridPos": gp,
        "description": desc,
        "fieldConfig": {"defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "gray", "value": None}, {"color": "red", "value": 0},
                {"color": "green", "value": 1}]},
            "mappings": [{"type": "value", "options": {
                "-1": {"text": "OTHER", "index": 0},
                "0": {"text": "BUILD FAILED", "index": 1},
                "1": {"text": "BUILD OK", "index": 2}}}],
            "noValue": "no data"}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "auto", "textMode": "name", "colorMode": "background",
                    "graphMode": "none", "justifyMode": "center"},
        "targets": [{"refId": "A", "datasource": PROM, "instant": True, "expr": expr,
                     "legendFormat": "{{project}} / {{environment}} / {{app}}"}],
    }

def table(title, gp, expr, desc="", extra_overrides=None, extra_transform=None):
    overrides = [{"matcher": {"id": "byName", "options": "Value"},
                  "properties": [
                      {"id": "displayName", "value": "Result"},
                      {"id": "custom.cellOptions", "value": {"type": "color-background"}},
                      {"id": "mappings", "value": [{"type": "value", "options": {
                          "-1": {"text": "OTHER", "color": "gray"},
                          "0": {"text": "FAILED", "color": "red"},
                          "1": {"text": "OK", "color": "green"}}}]},
                  ]}]
    overrides += (extra_overrides or [])
    trans = [{"id": "organize", "options": {
        "excludeByName": {"Time": True, "__name__": True, "job": True, "instance": True},
        "indexByName": {"project": 0, "environment": 1, "app": 2, "rank": 3, "commit": 4, "Value": 5},
        "renameByName": {}}}]
    trans += (extra_transform or [])
    return {
        "id": nid(), "type": "table", "title": title, "datasource": PROM, "gridPos": gp,
        "description": desc,
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True,
                        "cellOptions": {"type": "auto"}}}, "overrides": overrides},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                    "sortBy": [{"displayName": "app"}]},
        "targets": [{"refId": "A", "datasource": PROM, "instant": True, "format": "table", "expr": expr}],
        "transformations": trans,
    }


def build():
    _id[0] = 0
    sel = 'project=~"$project", environment=~"$environment"'
    P = []; y = 0

    P.append(row("Deployment builds  •  last 3 builds per application", y)); y += 1
    P.append(text_panel(g(0, y, 24, 3),
        "This is **build outcome**, not current uptime - see the "
        "[deployments dashboard](/d/deployments/deployments) for whether an app is "
        "running right now. The two can disagree: a failed build often leaves the "
        "*previous* container running, so the app looks fine while the build itself "
        "broke. Data comes straight from Coolify's own deployment-history table "
        "(`application_deployment_queues`) - its API doesn't expose this, so a cron "
        "job reads the table directly every 5 minutes. `rank=1` is the most recent "
        "build, `rank=2`/`3` the two before it."))
    y += 3

    P += [
        stat("Latest build: OK", g(0, y, 4, 4), f'count(coolify_build_success{{{sel}, rank="1"}} == 1)',
             unit="none", thresholds=[{"color": "green", "value": None}]),
        stat("Latest build: FAILED", g(4, y, 4, 4), f'count(coolify_build_success{{{sel}, rank="1"}} == 0)',
             unit="none", thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        stat("⚠ Failed build, still running", g(8, y, 6, 4),
             f'count(coolify_build_success{{{sel}, rank="1"}} == 0 and on(uuid) coolify_app_up == 1)',
             unit="none", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}],
             decimals=0),
        stat("Builder poller", g(14, y, 4, 4), "coolify_build_poll_success", unit="none",
             mappings=[{"type": "value", "options": {
                 "0": {"text": "FAILING", "index": 0}, "1": {"text": "OK", "index": 1}}}],
             thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
        stat("Last poll", g(18, y, 6, 4), "time() - coolify_build_last_poll_timestamp_seconds", unit="s",
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 600},
                         {"color": "red", "value": 1800}]),
    ]
    y += 4

    P.append(row("⚠ Build failed but the app is still running  (the silent-failure case)", y)); y += 1
    P.append(table("These builds failed - the container you're seeing is the old one",
        g(0, y, 24, 8),
        f'coolify_build_success{{{sel}, rank="1"}} == 0 and on(uuid) coolify_app_up == 1',
        desc="Latest deploy for this app failed AND its container is currently up - "
             "that's the previous successful build still serving traffic, not the one "
             "you just shipped."))
    y += 8

    P.append(row("Latest build status by application", y)); y += 1
    P.append(status_board("Most recent build per app  (rank = 1)",
        g(0, y, 24, 16), f'coolify_build_success{{{sel}, rank="1"}}',
        desc="Green = last build finished cleanly. Red = last build failed. "
             "Gray = cancelled or another non-terminal outcome."))
    y += 16

    P.append(row("Full build history  (last 3 per app)", y)); y += 1
    P.append(table("All recent builds", g(0, y, 24, 14),
        f'coolify_build_success{{{sel}}}',
        desc="Every build Coolify has recorded for each app in the last 3 attempts, "
             "newest first per app. Filter by column to find one quickly."))
    y += 14

    templating = {"list": [
        {"type": "query", "name": "project", "label": "Project", "datasource": PROM,
         "definition": 'label_values(coolify_build_success, project)',
         "query": {"qryType": 1, "query": 'label_values(coolify_build_success, project)',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
        {"type": "query", "name": "environment", "label": "Environment", "datasource": PROM,
         "definition": 'label_values(coolify_build_success, environment)',
         "query": {"qryType": 1, "query": 'label_values(coolify_build_success, environment)',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
    ]}

    dash = {
        "uid": "deployment-builds", "title": "deployment-builds",
        "tags": ["deployments", "coolify", "builds", "valura", "generated"],
        "timezone": "browser", "editable": True, "schemaVersion": 42,
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "weekStart": "", "preload": False,
        "refresh": "2m", "time": {"from": "now-24h", "to": "now"},
        "timepicker": {}, "templating": templating,
        "links": [{"title": "↔ deployments (live status)", "type": "link",
                   "url": "/d/deployments/deployments", "icon": "external link"}],
        "annotations": {"list": [{"builtIn": 1, "type": "dashboard",
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True, "hide": True, "name": "Annotations & Alerts"}]},
        "panels": P,
    }
    return dash


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    d = build()
    p = f"{out}/deployment-builds.json"
    json.dump(d, open(p, "w"), indent=2)
    open(p, "a").write("\n")
    print(f"wrote {p}  ({len(d['panels'])} panels)")
