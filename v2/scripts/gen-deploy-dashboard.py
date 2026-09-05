#!/usr/bin/env python3
"""deployments dashboard - one green/red box per Coolify application, across
every project and environment, so a deploy that silently failed in the
Coolify UI shows up here instead.

Data comes from scripts/coolify-deploy-status.py (a cron poller, since
Coolify's API has no push/webhook-out for status - see that script's
docstring for why this reports live container health rather than a deploy-
event history, which the API doesn't expose).
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
            "thresholds": {"mode": "absolute",
                           "steps": [{"color": "red", "value": None}, {"color": "green", "value": 1}]},
            "mappings": [{"type": "value", "options": {
                "0": {"text": "DOWN", "index": 0}, "1": {"text": "UP", "index": 1}}}],
            "noValue": "no data"}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "auto", "textMode": "name", "colorMode": "background",
                    "graphMode": "none", "justifyMode": "center"},
        "targets": [{"refId": "A", "datasource": PROM, "instant": True, "expr": expr,
                     "legendFormat": "{{project}} / {{environment}} / {{app}}"}],
    }

def table(title, gp, expr, desc=""):
    return {
        "id": nid(), "type": "table", "title": title, "datasource": PROM, "gridPos": gp,
        "description": desc,
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True,
                        "cellOptions": {"type": "auto"}}}, "overrides": [
            {"matcher": {"id": "byName", "options": "Value"},
             "properties": [{"id": "custom.hidden", "value": True}]},
        ]},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}, "sortBy": []},
        "targets": [{"refId": "A", "datasource": PROM, "instant": True, "format": "table", "expr": expr}],
        "transformations": [{"id": "organize", "options": {
            "excludeByName": {"Time": True, "__name__": True, "job": True, "Value": True},
            "indexByName": {"project": 0, "environment": 1, "app": 2, "status": 3, "uuid": 4},
            "renameByName": {}}}],
    }


def build():
    _id[0] = 0
    sel = 'project=~"$project", environment=~"$environment"'
    P = []; y = 0

    P.append(row("Deployments  •  latest status per application", y)); y += 1
    P.append(text_panel(g(0, y, 24, 2),
        "Green/red reflects each app's **live container status** in Coolify right now "
        "(`running:healthy` vs `exited`/`unhealthy`/etc.), refreshed every 2 minutes by "
        "a cron poller. Coolify's API has no deploy-history endpoint that returns data, "
        "so this is the closest available signal to \"did the last deploy leave it "
        "healthy\" - not a deploy-event log. If a box goes red right after you deploy, "
        "that's your failed-deploy signal."))
    y += 2

    P += [
        stat("Apps up", g(0, y, 4, 4), f'count(coolify_app_up{{{sel}}} == 1)', unit="none",
             thresholds=[{"color": "green", "value": None}]),
        stat("Apps down", g(4, y, 4, 4), f'count(coolify_app_up{{{sel}}} == 0)', unit="none",
             thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        stat("Total apps", g(8, y, 4, 4), f'count(coolify_app_up{{{sel}}})', unit="none"),
        stat("Poller", g(12, y, 4, 4), "coolify_poll_success", unit="none", graph="none",
             mappings=[{"type": "value", "options": {
                 "0": {"text": "FAILING", "index": 0}, "1": {"text": "OK", "index": 1}}}],
             thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
        stat("Last poll", g(16, y, 4, 4), "time() - coolify_last_poll_timestamp_seconds", unit="s",
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 300},
                         {"color": "red", "value": 900}],
             graph="none"),
        stat("Apps seen by poller", g(20, y, 4, 4), "coolify_poll_apps_total", unit="none"),
    ]
    y += 4

    P.append(status_board("Status by application  (filtered by Project / Environment above)",
        g(0, y, 24, 16), f'coolify_app_up{{{sel}}}',
        desc="Green = running. Red = stopped/crashed/exited. One box per app."))
    y += 16

    P.append(row("Down right now", y)); y += 1
    P.append(table("Apps not running", g(0, y, 24, 10),
        f'coolify_app_up{{{sel}}} == 0',
        desc="Every field is a label pulled straight off the metric - project, "
             "environment, app, uuid, status. Use the column filters to narrow down."))
    y += 10

    templating = {"list": [
        {"type": "query", "name": "project", "label": "Project", "datasource": PROM,
         "definition": 'label_values(coolify_app_up, project)',
         "query": {"qryType": 1, "query": 'label_values(coolify_app_up, project)',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
        {"type": "query", "name": "environment", "label": "Environment", "datasource": PROM,
         "definition": 'label_values(coolify_app_up, environment)',
         "query": {"qryType": 1, "query": 'label_values(coolify_app_up, environment)',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
    ]}

    dash = {
        "uid": "deployments", "title": "deployments",
        "tags": ["deployments", "coolify", "valura", "generated"],
        "timezone": "browser", "editable": True, "schemaVersion": 42,
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "weekStart": "", "preload": False,
        "refresh": "1m", "time": {"from": "now-6h", "to": "now"},
        "timepicker": {}, "templating": templating, "links": [],
        "annotations": {"list": [{"builtIn": 1, "type": "dashboard",
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True, "hide": True, "name": "Annotations & Alerts"}]},
        "panels": P,
    }
    return dash


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    d = build()
    p = f"{out}/deployments.json"
    json.dump(d, open(p, "w"), indent=2)
    open(p, "a").write("\n")
    print(f"wrote {p}  ({len(d['panels'])} panels)")
