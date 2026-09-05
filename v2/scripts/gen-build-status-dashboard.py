#!/usr/bin/env python3
"""deployment-builds dashboard - pass/fail of each Coolify app's last 3
builds, plus the full build log for the one you pick ($app + $rank -> a
Loki Logs panel). Status from coolify_build_success, logs from the
coolify_build_logs Loki stream - both produced by coolify-build-status.py.
"""
import json, sys

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}

# Same scoping as gen-deploy-dashboard.py - see that file's comment for why
# this filters by Coolify PROJECT rather than "environment".
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

# clicking a tile / row reloads THIS dashboard with that app+rank selected, so
# the chained $deployment_uuid var re-resolves and the Build log panel updates.
def _board_link(link_uid):
    return [{"title": "Show build log",
             "url": f"/d/{link_uid}?var-app=${{__field.labels.app}}&var-rank=${{__field.labels.rank}}&${{__url_time_range}}"}]

def _row_link(link_uid):
    return [{"title": "Show build log",
             "url": f"/d/{link_uid}?var-app=${{__data.fields.app}}&var-rank=${{__data.fields.rank}}&${{__url_time_range}}"}]

def status_board(gp, expr, link_uid):
    return {
        "id": nid(), "type": "stat", "title": "Latest build per app", "datasource": PROM, "gridPos": gp,
        "fieldConfig": {"defaults": {
            "color": {"mode": "thresholds"},
            "thresholds": {"mode": "absolute", "steps": [
                {"color": "gray", "value": None}, {"color": "red", "value": 0},
                {"color": "green", "value": 1}]},
            "mappings": [{"type": "value", "options": {
                "-1": {"text": "OTHER", "index": 0},
                "0": {"text": "FAILED", "index": 1},
                "1": {"text": "OK", "index": 2}}}],
            "links": _board_link(link_uid),
            "noValue": "no data"}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "auto", "textMode": "name", "colorMode": "background",
                    "graphMode": "none", "justifyMode": "center"},
        "targets": [{"refId": "A", "datasource": PROM, "instant": True, "expr": expr,
                     "legendFormat": "{{project}} / {{app}}"}],
    }

def table(title, gp, expr, link_uid):
    overrides = [
        {"matcher": {"id": "byName", "options": "Value"},
         "properties": [
             {"id": "displayName", "value": "Result"},
             {"id": "custom.cellOptions", "value": {"type": "color-background"}},
             {"id": "mappings", "value": [{"type": "value", "options": {
                 "-1": {"text": "OTHER", "color": "gray"},
                 "0": {"text": "FAILED", "color": "red"},
                 "1": {"text": "OK", "color": "green"}}}]},
         ]},
        {"matcher": {"id": "byName", "options": "app"},
         "properties": [{"id": "links", "value": _row_link(link_uid)}]},
    ]
    trans = [{"id": "organize", "options": {
        "excludeByName": {"Time": True, "__name__": True, "job": True, "instance": True,
                          "deployment_uuid": True, "uuid": True},
        "indexByName": {"project": 0, "environment": 1, "app": 2, "rank": 3, "commit": 4, "Value": 5},
        "renameByName": {}}}]
    return {
        "id": nid(), "type": "table", "title": title, "datasource": PROM, "gridPos": gp,
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True,
                        "cellOptions": {"type": "auto"}}}, "overrides": overrides},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                    "sortBy": [{"displayName": "app"}]},
        "targets": [{"refId": "A", "datasource": PROM, "instant": True, "format": "table", "expr": expr}],
        "transformations": trans,
    }

def build_log_panel(gp, scope):
    app_scope = f', project=~"{SCOPES[scope]["project_regex"]}"' if scope else ''
    return {
        "id": nid(), "type": "logs", "title": "Build log — $app  (build $rank)", "datasource": LOKI,
        "gridPos": gp, "pluginVersion": "12.3.2",
        "options": {"showTime": True, "showLabels": False, "showCommonLabels": False,
                    "wrapLogMessage": True, "prettifyLogMessage": False, "enableLogDetails": True,
                    "dedupStrategy": "none", "sortOrder": "Descending",
                    "enableInfiniteScrolling": True},
        "targets": [{"refId": "A", "datasource": LOKI, "maxLines": 5000,
                     "expr": '{job="coolify_build_logs", app="$app"} | deployment_uuid=~`$deployment_uuid`'}],
    }


def build(scope=None):
    _id[0] = 0
    if scope:
        sel = f'project=~"{SCOPES[scope]["project_regex"]}", project=~"$project"'
    else:
        sel = 'project=~"$project", environment=~"$environment"'
    uid = f"deployment-builds-{scope}" if scope else "deployment-builds"
    P = []; y = 0

    P.append(row("summary", y)); y += 1
    P += [
        stat("Latest build OK", g(0, y, 4, 4), f'count(coolify_build_success{{{sel}, rank="1"}} == 1)',
             unit="none", thresholds=[{"color": "green", "value": None}]),
        stat("Latest build failed", g(4, y, 4, 4), f'count(coolify_build_success{{{sel}, rank="1"}} == 0)',
             unit="none", thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        stat("Failed but still running", g(8, y, 6, 4),
             f'count(coolify_build_success{{{sel}, rank="1"}} == 0 and on(uuid) coolify_app_up == 1)',
             unit="none", thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1}],
             decimals=0),
        stat("Poller", g(14, y, 4, 4), "coolify_build_poll_success", unit="none",
             mappings=[{"type": "value", "options": {
                 "0": {"text": "FAILING", "index": 0}, "1": {"text": "OK", "index": 1}}}],
             thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
        stat("Last poll", g(18, y, 6, 4), "time() - coolify_build_last_poll_timestamp_seconds", unit="s",
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 600},
                         {"color": "red", "value": 1800}]),
    ]
    y += 4

    P.append(row("failed but still running", y)); y += 1
    P.append(table("", g(0, y, 24, 8),
        f'coolify_build_success{{{sel}, rank="1"}} == 0 and on(uuid) coolify_app_up == 1', uid))
    y += 8

    P.append(row("latest build", y)); y += 1
    P.append(status_board(g(0, y, 24, 16), f'coolify_build_success{{{sel}, rank="1"}}', uid))
    y += 16

    P.append(row("build log", y)); y += 1
    P.append(build_log_panel(g(0, y, 24, 18), scope))
    y += 18

    P.append(row("history", y)); y += 1
    P.append(table("", g(0, y, 24, 14), f'coolify_build_success{{{sel}}}', uid))
    y += 14

    project_def = (f'label_values(coolify_build_success{{project=~"{SCOPES[scope]["project_regex"]}"}}, project)'
                   if scope else 'label_values(coolify_build_success, project)')
    scope_filter = f'project=~"{SCOPES[scope]["project_regex"]}"' if scope else ""
    app_def = f'label_values(coolify_build_success{{{scope_filter}}}, app)' if scope else \
              'label_values(coolify_build_success, app)'
    uuid_def = f'label_values(coolify_build_success{{app="$app", rank=~"$rank"}}, deployment_uuid)'
    templating_list = [
        {"type": "query", "name": "project", "label": "Project", "datasource": PROM,
         "definition": project_def,
         "query": {"qryType": 1, "query": project_def,
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
        {"type": "query", "name": "app", "label": "Build log: app", "datasource": PROM,
         "definition": app_def,
         "query": {"qryType": 1, "query": app_def,
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": False, "multi": False, "refresh": 2, "sort": 1},
        {"type": "custom", "name": "rank", "label": "Build log: rank (1=latest)",
         "query": "1,2,3", "options": [
             {"text": "1", "value": "1", "selected": True},
             {"text": "2", "value": "2", "selected": False},
             {"text": "3", "value": "3", "selected": False}],
         "current": {"text": "1", "value": "1"}, "includeAll": False, "multi": False},
        {"type": "query", "name": "deployment_uuid", "datasource": PROM, "hide": 2,
         "definition": uuid_def,
         "query": {"qryType": 1, "query": uuid_def,
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": False, "multi": False, "refresh": 2},
    ]
    if not scope:
        templating_list.insert(1,
            {"type": "query", "name": "environment", "label": "Environment", "datasource": PROM,
             "definition": 'label_values(coolify_build_success, environment)',
             "query": {"qryType": 1, "query": 'label_values(coolify_build_success, environment)',
                       "refId": "PrometheusVariableQueryEditor-VariableQuery"},
             "includeAll": True, "multi": True, "allValue": ".*",
             "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1})
    templating = {"list": templating_list}

    deploy_link = f"/d/deployments-{scope}" if scope else "/d/deployments/deployments"
    links = [{"title": "↔ deployments (live status)", "type": "link",
              "url": deploy_link, "icon": "external link"}]
    if scope == "prod":
        links += [{"title": f"↔ deployment-builds-{s}", "type": "link",
                   "url": f"/d/deployment-builds-{s}", "icon": "external link"} for s in ("dev", "staging")]
    elif scope in ("dev", "staging"):
        other = "staging" if scope == "dev" else "dev"
        links.append({"title": f"↔ deployment-builds-{other}", "type": "link",
                      "url": f"/d/deployment-builds-{other}", "icon": "external link"})

    dash = {
        "uid": uid, "title": uid,
        "tags": ["deployments", "coolify", "builds", "valura", "generated"] + ([scope] if scope else []),
        "timezone": "browser", "editable": True, "schemaVersion": 42,
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "weekStart": "", "preload": False,
        "refresh": "2m", "time": {"from": "now-24h", "to": "now"},
        "timepicker": {}, "templating": templating,
        "links": links,
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
    p = f"{out}/deployments/deployment-builds.json"
    json.dump(d, open(p, "w"), indent=2)
    open(p, "a").write("\n")
    print(f"wrote {p}  ({len(d['panels'])} panels)")

    for scope, cfg in SCOPES.items():
        d = build(scope)
        folder_dir = f"{out}/{cfg['folder']}"
        os.makedirs(folder_dir, exist_ok=True)
        p = f"{folder_dir}/deployment-builds-{scope}.json"
        json.dump(d, open(p, "w"), indent=2)
        open(p, "a").write("\n")
        print(f"wrote {p}  ({len(d['panels'])} panels)")
