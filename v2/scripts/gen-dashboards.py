#!/usr/bin/env python3
"""Per-region service dashboards for the v2 stack, one per Coolify project.

Four sections only: metrics, logs, traces, network. $resource (multi) filters
every metrics/logs panel; $service picks the trace service. Clicking a series
reloads the dashboard scoped to that service.
"""
import json, sys

PROM = {"type": "prometheus", "uid": "prometheus"}
LOKI = {"type": "loki", "uid": "loki"}
JAEGER = {"type": "jaeger", "uid": "jaeger"}

REGIONS = {
    "dev-UAE": {"project": "valura-development", "tag": "UAE", "uid": "dev-uae",
               "sibling": ("dev-IND", "dev-ind"), "folder": "dev",
               "box": "valura-dev", "host": "dev-server-1", "hostip": "10.200.2.51",
               "hostlabel": "dev host  •  10.200.2.51  (shared by dev-UAE + dev-IND)"},
    "dev-IND": {"project": "global-valura-dev", "tag": "IND", "uid": "dev-ind",
               "sibling": ("dev-UAE", "dev-uae"), "folder": "dev",
               "box": "valura-dev", "host": "dev-server-1", "hostip": "10.200.2.51",
               "hostlabel": "dev host  •  10.200.2.51  (shared by dev-UAE + dev-IND)"},
    "stg-UAE": {"project": "valura-uae-staging", "tag": "UAE staging", "uid": "stg-uae",
               "sibling": ("stg-IND", "stg-ind"), "folder": "staging",
               "box": "uae-staging", "host": "uae-stg", "hostip": "10.200.2.56",
               "hostlabel": "staging host  •  10.200.2.56 (UAE)"},
    "stg-IND": {"project": "global-valura-staging", "tag": "IND staging", "uid": "stg-ind",
               "sibling": ("stg-UAE", "stg-uae"), "folder": "staging",
               "box": "valura-ind-stg", "host": "ind-stg", "hostip": "10.200.2.57",
               "hostlabel": "staging host  •  10.200.2.57 (IND)"},
    "partner-apps": {"project": "partner-apps", "tag": "Partner Apps", "uid": "partner-apps",
               "sibling": None, "folder": "non-prod",
               "box": "partner-apps", "host": "edge", "hostip": "10.200.1.2",
               "hostlabel": "partner-apps host  •  10.200.1.2"},
    "prod-UAE": {"project": "valura-prod", "tag": "UAE prod", "uid": "prod-uae",
               "sibling": None, "folder": "prod",
               "box": "valura-prod", "host": "uae-prod", "hostip": "10.200.2.54",
               "hostlabel": "production host  •  10.200.2.54 (UAE)",
               "note": "**This is a production box** - treat restart-triggering changes "
                       "here with extra care."},
}

_id = [0]
def nid():
    _id[0] += 1
    return _id[0]

def g(x, y, w, h):
    return {"x": x, "y": y, "w": w, "h": h}

# a data link that re-opens THIS dashboard filtered to the clicked service
def drill(uid, label_ref):
    return [{
        "title": "Focus this service",
        "url": f"/d/{uid}?var-resource=${{{label_ref}}}&${{__url_time_range}}",
    }]

RES = "container_label_coolify_resourceName"

def ts(title, gp, targets, unit="short", stack=False, fill=8, minv=None,
       desc="", drilldash=None, drillref=RES, decimals=None, legend_calcs=("last","max","mean")):
    defaults = {"unit": unit, "custom": {
        "drawStyle": "line", "lineWidth": 1, "fillOpacity": fill,
        "showPoints": "never", "spanNulls": True, "gradientMode": "opacity",
        "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}
    if minv is not None: defaults["min"] = minv
    if decimals is not None: defaults["decimals"] = decimals
    if drilldash: defaults["links"] = drill(drilldash, drillref)
    return {
        "id": nid(), "type": "timeseries", "title": title, "datasource": PROM,
        "gridPos": gp, "description": desc,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom",
                               "calcs": list(legend_calcs)},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": targets,
    }

def loki_ts(title, gp, expr, legend, unit="short", stack=False, bars=False, overrides=None, desc=""):
    custom = {"drawStyle": "bars" if bars else "line", "lineWidth": 0 if bars else 1,
              "fillOpacity": 80 if bars else 12,
              "stacking": {"mode": "normal" if stack else "none", "group": "A"}}
    return {
        "id": nid(), "type": "timeseries", "title": title, "datasource": LOKI,
        "gridPos": gp, "description": desc,
        "fieldConfig": {"defaults": {"unit": unit, "custom": custom}, "overrides": overrides or []},
        "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr,
                     "legendFormat": legend, "queryType": "range"}],
    }

def stat(title, gp, expr, ds=PROM, unit="short", thresholds=None, is_loki=False,
         graph="area", decimals=None):
    t = {"refId": "A", "datasource": ds, "expr": expr}
    if is_loki: t["queryType"] = "instant"
    else: t["instant"] = True
    defaults = {"unit": unit, "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute",
                               "steps": thresholds or [{"color": "text", "value": None}]}}
    if decimals is not None: defaults["decimals"] = decimals
    return {
        "id": nid(), "type": "stat", "title": title, "datasource": ds, "gridPos": gp,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "auto", "textMode": "auto", "colorMode": "value",
                    "graphMode": graph, "justifyMode": "auto"},
        "targets": [t],
    }

def logs_panel(title, gp, expr, desc="", labels=True):
    # Options match the imported dashboards that render correctly. Target shape:
    # no queryType, has maxLines, double-quoted regex. The expr must never
    # resolve to an empty `|~ ""` - Grafana's frontend LogQL parser errors the
    # whole panel on that, so callers pass `|~ "(?i)$search"` not `|~ "$search"`.
    return {
        "id": nid(), "type": "logs", "title": title, "datasource": LOKI,
        "gridPos": gp, "description": desc, "pluginVersion": "12.3.2",
        "options": {"showTime": True, "showLabels": labels, "showCommonLabels": False,
                    "wrapLogMessage": True, "prettifyLogMessage": True,
                    "enableLogDetails": True, "dedupStrategy": "none",
                    "sortOrder": "Descending", "enableInfiniteScrolling": False,
                    "showControls": False},
        "targets": [{"refId": "A", "datasource": LOKI, "expr": expr,
                     "maxLines": 500, "legendFormat": ""}],
    }

def table(title, gp, targets, ds=PROM, desc="", overrides=None, transformations=None):
    return {
        "id": nid(), "type": "table", "title": title, "datasource": ds, "gridPos": gp,
        "description": desc,
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True,
                        "cellOptions": {"type": "auto"}}}, "overrides": overrides or []},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                    "sortBy": []},
        "targets": targets,
        "transformations": transformations or [],
    }

def row(title, y):
    return {"id": nid(), "type": "row", "title": title, "collapsed": False,
            "gridPos": g(0, y, 24, 1), "panels": []}

def build(name, cfg):
    proj = cfg["project"]; tag = cfg["tag"]; uid = cfg["uid"]
    box = cfg["box"]; host = cfg["host"]
    _id[0] = 0

    cad  = f'container_label_coolify_projectName="{proj}", box="{box}"'
    cadr = cad + f', {RES}=~"$resource"'
    node = f'job="node-fleet", box="{box}"'
    lbase = f'coolify_project="{proj}", host="{host}"'
    lsel  = lbase + ', coolify_resource=~"$resource"'

    P = []; y = 0

    # ================================ metrics ================================
    P.append(row("metrics", y)); y += 1
    P += [
        stat("Running containers", g(0, y, 3, 4), f'count(container_last_seen{{{cad}}})',
             thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}]),
        stat("Restarts (1h)", g(3, y, 3, 4),
             f'sum(changes(container_start_time_seconds{{{cad}}}[1h])) or vector(0)',
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1},
                         {"color": "red", "value": 5}]),
        stat("CPU cores", g(6, y, 3, 4), f'sum(rate(container_cpu_usage_seconds_total{{{cad}}}[5m]))',
             unit="none", decimals=2),
        stat("Memory", g(9, y, 3, 4), f'sum(container_memory_working_set_bytes{{{cad}}})', unit="bytes"),
        stat("Errors (5m)", g(12, y, 3, 4),
             f'sum(count_over_time({{{lbase}, level=~"error|fatal"}} [5m]))',
             ds=LOKI, unit="none", is_loki=True,
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1},
                         {"color": "red", "value": 50}]),
        stat("Warnings (5m)", g(15, y, 3, 4),
             f'sum(count_over_time({{{lbase}, level="warn"}} [5m]))',
             ds=LOKI, unit="none", is_loki=True,
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 20}]),
        stat("Log lines/min", g(18, y, 3, 4), f'sum(count_over_time({{{lbase}}} [1m]))',
             ds=LOKI, unit="none", is_loki=True),
        stat("Services reporting", g(21, y, 3, 4),
             f'count(count by ({RES}) (container_last_seen{{{cad}}}))', unit="none"),
    ]
    y += 4

    if not cfg.get("skip_service_status"):
        P.append({
            "id": nid(), "type": "stat", "title": "Service status", "datasource": PROM,
            "gridPos": g(0, y, 24, 7),
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
            "targets": [{"refId": "A", "datasource": PROM, "instant": True,
                         "expr": f'max by ({RES}) ((time() - container_last_seen{{{cad}}}) < 60)',
                         "legendFormat": f"{{{{{RES}}}}}"}],
        })
        y += 7

    P.append(ts("Restarts by service", g(0, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by ({RES}) (changes(container_start_time_seconds{{{cadr}}}[1h]))',
          "legendFormat": f"{{{{{RES}}}}}"}], unit="none", fill=0, drilldash=uid))
    P.append(ts("OOM events by service", g(12, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by ({RES}) (increase(container_oom_events_total{{{cadr}}}[$__interval]))',
          "legendFormat": f"{{{{{RES}}}}}"}], unit="none", fill=0, drilldash=uid))
    y += 8

    P.append(ts("CPU cores by service", g(0, y, 24, 9),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by ({RES}) (rate(container_cpu_usage_seconds_total{{{cadr}}}[$__rate_interval]))',
          "legendFormat": f"{{{{{RES}}}}}"}], unit="none", stack=True, decimals=3, drilldash=uid))
    y += 9

    P.append(ts("Memory (working set) by service", g(0, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by ({RES}) (container_memory_working_set_bytes{{{cadr}}})',
          "legendFormat": f"{{{{{RES}}}}}"}], unit="bytes", stack=True, drilldash=uid))
    P.append(ts("Memory vs limit (%)", g(12, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": (f'100 * sum by ({RES}) (container_memory_working_set_bytes{{{cadr}}}) '
                   f'/ (sum by ({RES}) (container_spec_memory_limit_bytes{{{cadr}}}) > 0)'),
          "legendFormat": f"{{{{{RES}}}}}"}], unit="percent", fill=3, drilldash=uid))
    y += 8

    P += [
        stat("Host CPU busy", g(0, y, 4, 4),
             f'100 * (1 - avg(rate(node_cpu_seconds_total{{{node}, mode="idle"}}[5m])))',
             unit="percent", thresholds=[{"color": "green", "value": None},
                                         {"color": "orange", "value": 80}, {"color": "red", "value": 92}]),
        stat("Load (1m)", g(4, y, 4, 4), f'node_load1{{{node}}}', unit="none", graph="none"),
        stat("RAM used", g(8, y, 4, 4),
             f'100 * (1 - node_memory_MemAvailable_bytes{{{node}}} / node_memory_MemTotal_bytes{{{node}}})',
             unit="percent", thresholds=[{"color": "green", "value": None},
                                         {"color": "orange", "value": 85}, {"color": "red", "value": 95}]),
        stat("RAM total", g(12, y, 4, 4), f'node_memory_MemTotal_bytes{{{node}}}', unit="bytes", graph="none"),
        stat("Root FS used", g(16, y, 4, 4),
             f'100 * (1 - node_filesystem_avail_bytes{{{node}, mountpoint="/"}} / node_filesystem_size_bytes{{{node}, mountpoint="/"}})',
             unit="percent", thresholds=[{"color": "green", "value": None},
                                         {"color": "orange", "value": 80}, {"color": "red", "value": 90}]),
        stat("Host uptime", g(20, y, 4, 4), f'time() - node_boot_time_seconds{{{node}}}', unit="s", graph="none"),
    ]
    y += 4
    P.append(ts("Host CPU by mode", g(0, y, 12, 7),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by (mode) (rate(node_cpu_seconds_total{{{node}, mode!="idle"}}[$__rate_interval]))',
          "legendFormat": "{{mode}}"}], stack=True, minv=0))
    P.append(ts("Host memory", g(12, y, 12, 7),
        [{"refId": "A", "datasource": PROM, "expr": f'node_memory_MemTotal_bytes{{{node}}}', "legendFormat": "total"},
         {"refId": "B", "datasource": PROM,
          "expr": f'node_memory_MemTotal_bytes{{{node}}} - node_memory_MemAvailable_bytes{{{node}}}', "legendFormat": "used"}],
        unit="bytes", fill=3))
    y += 7
    P.append(ts("Host disk I/O", g(0, y, 24, 6),
        [{"refId": "A", "datasource": PROM,
          "expr": f'rate(node_disk_read_bytes_total{{{node}}}[$__rate_interval])', "legendFormat": "read {{device}}"},
         {"refId": "B", "datasource": PROM,
          "expr": f'- rate(node_disk_written_bytes_total{{{node}}}[$__rate_interval])', "legendFormat": "write {{device}}"}],
        unit="Bps", fill=3))
    y += 6

    # ================================= logs =================================
    P.append(row("logs", y)); y += 1
    P.append(loki_ts("Log volume by level", g(0, y, 12, 7),
        f'sum by (level) (count_over_time({{{lsel}}}[$__interval]))',
        "{{level}}", stack=True, bars=True,
        overrides=[
          {"matcher": {"id": "byName", "options": "error"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "red"}}]},
          {"matcher": {"id": "byName", "options": "fatal"}, "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "dark-red"}}]},
          {"matcher": {"id": "byName", "options": "warn"},  "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "orange"}}]},
          {"matcher": {"id": "byName", "options": "info"},  "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": "green"}}]},
        ]))
    P.append(loki_ts("Error / warn rate by service", g(12, y, 12, 7),
        f'sum by (coolify_resource) (count_over_time({{{lsel}}} |~ "(?i)(error|warn|fatal|exception|critical)" [$__interval]))',
        "{{coolify_resource}}", stack=True))
    y += 7
    P.append(logs_panel("Errors, warnings & exceptions", g(0, y, 24, 12),
        f'{{{lsel}}} |~ "(?i)(error|warn|fatal|critical|exception|traceback|panic)"'))
    y += 12
    P.append(logs_panel("All logs", g(0, y, 24, 16), f'{{{lsel}}}'))
    y += 16

    # ================================ traces ================================
    P.append(row("traces", y)); y += 1
    P.append(ts("Request rate by service", g(0, y, 8, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": 'sum by (service_name) (rate(traces_spanmetrics_calls_total[$__rate_interval]))',
          "legendFormat": "{{service_name}}"}], unit="reqps"))
    P.append(ts("Error rate by service", g(8, y, 8, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": 'sum by (service_name) (rate(traces_spanmetrics_calls_total{status_code="STATUS_CODE_ERROR"}[$__rate_interval]))',
          "legendFormat": "{{service_name}}"}], unit="reqps"))
    P.append(ts("p95 latency by service", g(16, y, 8, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": 'histogram_quantile(0.95, sum by (le, service_name) (rate(traces_spanmetrics_latency_bucket[$__rate_interval])))',
          "legendFormat": "{{service_name}}"}], unit="ms"))
    y += 8
    P.append({"id": nid(), "type": "table", "title": "Recent traces",
        "datasource": JAEGER, "gridPos": g(0, y, 24, 8),
        "targets": [{"refId": "A", "datasource": JAEGER, "queryType": "search",
                     "service": "$service", "limit": 20}]})
    y += 8

    # =============================== network ================================
    P.append(row("network", y)); y += 1
    P.append(ts("Network RX by service", g(0, y, 12, 7),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by ({RES}) (rate(container_network_receive_bytes_total{{{cadr}}}[$__rate_interval]))',
          "legendFormat": f"{{{{{RES}}}}}"}], unit="Bps", stack=True, fill=4, drilldash=uid))
    P.append(ts("Network TX by service", g(12, y, 12, 7),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by ({RES}) (rate(container_network_transmit_bytes_total{{{cadr}}}[$__rate_interval]))',
          "legendFormat": f"{{{{{RES}}}}}"}], unit="Bps", stack=True, fill=4, drilldash=uid))
    y += 7
    P.append(ts("Host network", g(0, y, 24, 7),
        [{"refId": "A", "datasource": PROM,
          "expr": f'rate(node_network_receive_bytes_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "rx {{device}}"},
         {"refId": "B", "datasource": PROM,
          "expr": f'- rate(node_network_transmit_bytes_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "tx {{device}}"}], unit="Bps", fill=3))
    y += 7

    # ---------------------------------------------------------------- vars ---
    templating = {"list": [
        {"type": "constant", "name": "project", "label": "Coolify project",
         "query": proj, "current": {"text": proj, "value": proj}, "hide": 2},
        {"type": "query", "name": "resource", "label": "Service", "datasource": PROM,
         "definition": f'label_values(container_last_seen{{{cad}}}, {RES})',
         "query": {"qryType": 1, "query": f'label_values(container_last_seen{{{cad}}}, {RES})',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": True, "multi": True, "allValue": ".*",
         "current": {"text": "All", "value": "$__all"}, "refresh": 2, "sort": 1},
        {"type": "query", "name": "service", "label": "Trace service", "datasource": PROM,
         "definition": 'label_values(traces_spanmetrics_calls_total, service_name)',
         "query": {"qryType": 1, "query": 'label_values(traces_spanmetrics_calls_total, service_name)',
                   "refId": "PrometheusVariableQueryEditor-VariableQuery"},
         "includeAll": False, "multi": False,
         "current": {"text": "", "value": ""}, "refresh": 2, "sort": 1},
    ]}

    links = []
    if cfg.get("sibling"):
        sib_name, sib_uid = cfg["sibling"]
        links.append({"title": f"↔ {sib_name}", "type": "link",
                      "url": f"/d/{sib_uid}/{sib_uid}?${{__url_time_range}}",
                      "icon": "external link", "tooltip": f"switch to {sib_name}"})
    links += [
        {"title": "Jaeger UI", "type": "link", "url": "https://jaeger-infra.valura.co.in/",
         "icon": "external link", "targetBlank": True},
        {"title": "Explore logs", "type": "link",
         "url": f'/explore?left={{"datasource":"loki","queries":[{{"expr":"{{coolify_project=\\"{proj}\\", host=\\"{host}\\"}}"}}],"range":{{"from":"now-1h","to":"now"}}}}',
         "icon": "external link", "targetBlank": True},
    ]
    dash = {
        "uid": uid, "title": name,
        "tags": ["dev", tag.lower().replace(" ", "-"), "valura", "generated"],
        "timezone": "browser", "editable": True, "schemaVersion": 42,
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "weekStart": "", "preload": False,
        "refresh": "30s", "time": {"from": "now-3h", "to": "now"},
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
    for name, cfg in REGIONS.items():
        d = build(name, cfg)
        folder_dir = f"{out}/{cfg['folder']}"
        os.makedirs(folder_dir, exist_ok=True)
        p = f"{folder_dir}/{cfg['uid']}.json"
        json.dump(d, open(p, "w"), indent=2)
        open(p, "a").write("\n")
        print(f"wrote {p}  ({len(d['panels'])} panels)")
