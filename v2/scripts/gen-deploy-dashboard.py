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

# Coolify's own "environment" field is basically always "production" regardless
# of which of these three an app belongs to (verified live) - it's an internal
# Coolify concept, unrelated to our dev/staging/prod split. So the scoped
# dashboards below filter by Coolify PROJECT name instead. Note the casing here
# is the real Coolify project name (from the API/DB), which differs from the
# lowercase `coolify.projectName` docker-label slug used elsewhere in this repo
# for cAdvisor filtering - verified against live label values, not assumed.
SCOPES = {
    "dev":     {"folder": "dev",     "project_regex": "Valura-development|global-valura-dev"},
    "staging": {"folder": "staging", "project_regex": "valura-UAE-staging|global-valura-staging"},
    "prod":    {"folder": "prod",    "project_regex": "valura-prod"},
}

_id = [0]
def nid():
    _id[0] += 1
    return _id[0]

def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}

def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False,
            "gridPos": g(0, y, 24, 1), "panels": []}

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


def build(scope=None):
    _id[0] = 0
    if scope:
        sel = f'project=~"{SCOPES[scope]["project_regex"]}", project=~"$project"'
    else:
        sel = 'project=~"$project", environment=~"$environment"'
    P = []; y = 0

    P.append(row("status", y)); y += 1
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

    P.append(status_board("Status by application", g(0, y, 24, 16), f'coolify_app_up{{{sel}}}'))
    y += 16

    P.append(row("down", y)); y += 1
    P.append(table("Apps not running", g(0, y, 24, 10), f'coolify_app_up{{{sel}}} == 0'))
    y += 10

    project_def = (f'label_values(coolify_app_up{{project=~"{SCOPES[scope]["project_regex"]}"}}, project)'
                   if scope else 'label_values(coolify_app_up, project)')
    templating_list = [
        {"type": "query", "name": "project", "label": "Project", "datasource": PROM,
         "definition": project_def,
         "query": {"qryType": 1, "query": project_def,
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
    ]
    if not scope:
        templating_list.append(
            {"type": "query", "name": "environment", "label": "Environment", "datasource": PROM,
             "definition": 'label_values(coolify_app_up, environment)',
             "query": {"qryType": 1, "query": 'label_values(coolify_app_up, environment)',
                       "refId": "PrometheusVariableQueryEditor-VariableQuery"},
             "includeAll": True, "multi": True, "allValue": ".*",
             "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1})
    templating = {"list": templating_list}

    uid = f"deployments-{scope}" if scope else "deployments"
    links = []
    if scope == "prod":
        # Prod-View sees everything, so cross-links to dev/staging are safe from here.
        links = [{"title": f"↔ deployments-{s}", "type": "link", "url": f"/d/deployments-{s}",
                  "icon": "external link"} for s in ("dev", "staging")]
    elif scope in ("dev", "staging"):
        other = "staging" if scope == "dev" else "dev"
        links = [{"title": f"↔ deployments-{other}", "type": "link", "url": f"/d/deployments-{other}",
                  "icon": "external link"}]

    dash = {
        "uid": uid, "title": uid,
        "tags": ["deployments", "coolify", "valura", "generated"] + ([scope] if scope else []),
        "timezone": "browser", "editable": True, "schemaVersion": 42,
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "weekStart": "", "preload": False,
        "refresh": "1m", "time": {"from": "now-6h", "to": "now"},
        "timepicker": {}, "templating": templating, "links": links,
        "annotations": {"list": [{"builtIn": 1, "type": "dashboard",
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True, "hide": True, "name": "Annotations & Alerts"}]},
        "panels": P,
    }
    return dash


if __name__ == "__main__":
    import os
    out = sys.argv[1] if len(sys.argv) > 1 else "."

    d = build()
    p = f"{out}/deployments/deployments.json"
    json.dump(d, open(p, "w"), indent=2)
    open(p, "a").write("\n")
    print(f"wrote {p}  ({len(d['panels'])} panels)")

    for scope, cfg in SCOPES.items():
        d = build(scope)
        folder_dir = f"{out}/{cfg['folder']}"
        os.makedirs(folder_dir, exist_ok=True)
        p = f"{folder_dir}/deployments-{scope}.json"
        json.dump(d, open(p, "w"), indent=2)
        open(p, "a").write("\n")
        print(f"wrote {p}  ({len(d['panels'])} panels)")
