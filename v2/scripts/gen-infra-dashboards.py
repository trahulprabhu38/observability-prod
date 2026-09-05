#!/usr/bin/env python3
"""infra/* dashboards - one per physical/virtual server we have access to.

Unlike gen-dashboards.py (one dashboard per Coolify PROJECT, container-level),
these are one dashboard per HOST: is it up, and what's its OS-level resource
usage (CPU/RAM/disk/network/uptime) - plus, where cAdvisor/textfile data
exists on that box, a rollup of total container load it's carrying.

Servers covered = every box with a live node-exporter target in
prometheus/targets/node-fleet.yml, plus .52 itself (job="node", static). The
"dubai" cAdvisor-only target is excluded - it's been unreachable since the old
stack (see docs/dev-dashboards.md) and has no node-exporter, so there's no
host to build a usage dashboard for.
"""
import json, sys

PROM = {"type": "prometheus", "uid": "prometheus"}

HOSTS = {
    "infra-observability": {"box": "observability", "ip": "10.200.2.52", "job": "node",
        "cjob": "cadvisor", "uid": "infra-observability", "folder": "non-prod",
        "label": "Observability stack host (Prometheus/Loki/Jaeger/Grafana)"},
    "infra-dev": {"box": "valura-dev", "ip": "10.200.2.51", "job": "node-fleet",
        "cjob": "cadvisor-fleet", "uid": "infra-dev", "folder": "dev",
        "label": "Dev  •  shared by dev-UAE + dev-IND"},
    "infra-stg-uae": {"box": "uae-staging", "ip": "10.200.2.56", "job": "node-fleet",
        "cjob": "cadvisor-fleet", "uid": "infra-stg-uae", "folder": "staging",
        "label": "UAE staging"},
    "infra-stg-ind": {"box": "valura-ind-stg", "ip": "10.200.2.57", "job": "node-fleet",
        "cjob": "cadvisor-fleet", "uid": "infra-stg-ind", "folder": "staging",
        "label": "IND staging"},
    "infra-partner-apps": {"box": "partner-apps", "ip": "10.200.1.2", "job": "node-fleet",
        "cjob": "cadvisor-fleet", "uid": "infra-partner-apps", "folder": "non-prod",
        "label": "Partner-apps  •  also runs the Coolify control plane"},
    "infra-prod-uae": {"box": "valura-prod", "ip": "10.200.2.54", "job": "node-fleet",
        "cjob": "cadvisor-fleet", "uid": "infra-prod-uae", "folder": "prod",
        "label": "UAE production", "note": "**Production box** - view only."},
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

def text_panel(gp, md, transparent=False):
    return {"id": nid(), "type": "text", "gridPos": gp, "transparent": transparent,
            "options": {"mode": "markdown", "content": md}}

def stat(title, gp, expr, unit="short", thresholds=None, decimals=None, graph="area",
         mappings=None, color_mode="value", instant=True):
    defaults = {"unit": unit, "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute",
                               "steps": thresholds or [{"color": "text", "value": None}]}}
    if decimals is not None: defaults["decimals"] = decimals
    if mappings: defaults["mappings"] = mappings
    return {
        "id": nid(), "type": "stat", "title": title, "datasource": PROM, "gridPos": gp,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                    "orientation": "auto", "textMode": "auto", "colorMode": color_mode,
                    "graphMode": graph, "justifyMode": "auto"},
        "targets": [{"refId": "A", "datasource": PROM, "expr": expr, "instant": instant}],
    }

def ts(title, gp, targets, unit="short", stack=False, fill=8, minv=None, desc="", decimals=None):
    defaults = {"unit": unit, "custom": {
        "drawStyle": "line", "lineWidth": 1, "fillOpacity": fill,
        "showPoints": "never", "spanNulls": True, "gradientMode": "opacity",
        "stacking": {"mode": "normal" if stack else "none", "group": "A"}}}
    if minv is not None: defaults["min"] = minv
    if decimals is not None: defaults["decimals"] = decimals
    return {
        "id": nid(), "type": "timeseries", "title": title, "datasource": PROM,
        "gridPos": gp, "description": desc,
        "fieldConfig": {"defaults": defaults, "overrides": []},
        "options": {"legend": {"displayMode": "table", "placement": "bottom",
                               "calcs": ["last", "max", "mean"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "targets": targets,
    }

def table(title, gp, targets, desc="", unit=None, hide_fields=None, transformations=None):
    overrides = []
    if unit:
        overrides.append({"matcher": {"id": "byName", "options": "Value"},
                           "properties": [{"id": "unit", "value": unit},
                                          {"id": "decimals", "value": 1}]})
    trans = list(transformations or [])
    if hide_fields:
        trans.append({"id": "organize", "options": {
            "excludeByName": {f: True for f in hide_fields}, "indexByName": {}, "renameByName": {}}})
    return {
        "id": nid(), "type": "table", "title": title, "datasource": PROM, "gridPos": gp,
        "description": desc,
        "fieldConfig": {"defaults": {"custom": {"align": "auto", "filterable": True,
                        "cellOptions": {"type": "auto"}}}, "overrides": overrides},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False},
                    "sortBy": [{"displayName": "Value", "desc": True}]},
        "targets": targets,
        "transformations": trans,
    }


def build(name, cfg):
    box, ip, job, cjob = cfg["box"], cfg["ip"], cfg["job"], cfg["cjob"]
    uid = cfg["uid"]
    _id[0] = 0
    node = f'job="{job}", box="{box}"'
    cad = f'job="{cjob}", box="{box}"'

    P = []; y = 0

    P.append(row(f"{cfg['label']}  •  {ip}", y)); y += 1
    if cfg.get("note"):
        P.append(text_panel(g(0, y, 24, 2), cfg["note"])); y += 2

    # ---- status: up/down ----
    P.append(stat("Status", g(0, y, 4, 5), f'up{{{node}}}', unit="none", graph="none",
        mappings=[{"type": "value", "options": {
            "0": {"text": "DOWN", "index": 0}, "1": {"text": "UP", "index": 1}}}],
        thresholds=[{"color": "red", "value": None}, {"color": "green", "value": 1}],
        color_mode="background"))
    P += [
        stat("CPU busy", g(4, y, 4, 5),
             f'100 * (1 - avg(rate(node_cpu_seconds_total{{{node}, mode="idle"}}[5m])))',
             unit="percent", thresholds=[{"color": "green", "value": None},
                                         {"color": "orange", "value": 80}, {"color": "red", "value": 92}]),
        stat("RAM used", g(8, y, 4, 5),
             f'100 * (1 - node_memory_MemAvailable_bytes{{{node}}} / node_memory_MemTotal_bytes{{{node}}})',
             unit="percent", thresholds=[{"color": "green", "value": None},
                                         {"color": "orange", "value": 85}, {"color": "red", "value": 95}]),
        stat("Root FS used", g(12, y, 4, 5),
             f'100 * (1 - node_filesystem_avail_bytes{{{node}, mountpoint="/"}} / node_filesystem_size_bytes{{{node}, mountpoint="/"}})',
             unit="percent", thresholds=[{"color": "green", "value": None},
                                         {"color": "orange", "value": 80}, {"color": "red", "value": 90}]),
        stat("Load (1m / 5m / 15m)", g(16, y, 4, 5), f'node_load1{{{node}}}', unit="none", graph="none"),
        stat("Uptime", g(20, y, 4, 5), f'time() - node_boot_time_seconds{{{node}}}', unit="s", graph="none"),
    ]
    y += 5

    # ---- containers this host is carrying (rollup, not per-service - see the
    # project dashboard for that) ----
    P.append(row("Containers on this host", y)); y += 1
    P += [
        stat("Containers running", g(0, y, 6, 4),
             f'count(container_last_seen{{{cad}}})', unit="none"),
        stat("Total container CPU cores", g(6, y, 6, 4),
             f'sum(rate(container_cpu_usage_seconds_total{{{cad}}}[5m]))', unit="none", decimals=2),
        stat("Total container memory", g(12, y, 6, 4),
             f'sum(container_memory_working_set_bytes{{{cad}}})', unit="bytes"),
        stat("Restarts (1h)", g(18, y, 6, 4),
             f'sum(changes(container_start_time_seconds{{{cad}}}[1h])) or vector(0)',
             thresholds=[{"color": "green", "value": None}, {"color": "orange", "value": 1},
                         {"color": "red", "value": 5}]),
    ]
    y += 4

    # ---- CPU ----
    P.append(row("CPU", y)); y += 1
    P.append(ts("CPU by mode", g(0, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'sum by (mode) (rate(node_cpu_seconds_total{{{node}, mode!="idle"}}[$__rate_interval]))',
          "legendFormat": "{{mode}}"}], stack=True, minv=0))
    P.append(ts("Load average", g(12, y, 12, 8),
        [{"refId": "A", "datasource": PROM, "expr": f'node_load1{{{node}}}', "legendFormat": "1m"},
         {"refId": "B", "datasource": PROM, "expr": f'node_load5{{{node}}}', "legendFormat": "5m"},
         {"refId": "C", "datasource": PROM, "expr": f'node_load15{{{node}}}', "legendFormat": "15m"}],
        unit="none", minv=0))
    y += 8

    # ---- memory ----
    P.append(row("Memory", y)); y += 1
    P.append(ts("Memory breakdown", g(0, y, 12, 8),
        [{"refId": "A", "datasource": PROM, "expr": f'node_memory_MemTotal_bytes{{{node}}}', "legendFormat": "total"},
         {"refId": "B", "datasource": PROM,
          "expr": f'node_memory_MemTotal_bytes{{{node}}} - node_memory_MemAvailable_bytes{{{node}}}', "legendFormat": "used"},
         {"refId": "C", "datasource": PROM, "expr": f'node_memory_Cached_bytes{{{node}}}', "legendFormat": "cached"},
         {"refId": "D", "datasource": PROM, "expr": f'node_memory_Buffers_bytes{{{node}}}', "legendFormat": "buffers"}],
        unit="bytes", fill=3))
    P.append(ts("Swap used", g(12, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'node_memory_SwapTotal_bytes{{{node}}} - node_memory_SwapFree_bytes{{{node}}}',
          "legendFormat": "swap used"}], unit="bytes", fill=6, minv=0))
    y += 8

    # ---- disk ----
    P.append(row("Disk", y)); y += 1
    P.append(table("Filesystem usage by mountpoint", g(0, y, 12, 8),
        [{"refId": "A", "datasource": PROM, "instant": True, "format": "table",
          "expr": (f'100 * (1 - node_filesystem_avail_bytes{{{node}, fstype=~"ext4|xfs|btrfs|zfs"}} '
                   f'/ node_filesystem_size_bytes{{{node}, fstype=~"ext4|xfs|btrfs|zfs"}})'),
          "legendFormat": "{{mountpoint}}"}],
        desc="% used per real mountpoint (excludes tmpfs/overlay/squashfs loop devices).",
        unit="percent",
        hide_fields=["Time", "__name__", "box", "device", "env", "fstype", "instance", "job", "kind"]))
    P.append(ts("Disk I/O", g(12, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'rate(node_disk_read_bytes_total{{{node}}}[$__rate_interval])', "legendFormat": "read {{device}}"},
         {"refId": "B", "datasource": PROM,
          "expr": f'- rate(node_disk_written_bytes_total{{{node}}}[$__rate_interval])', "legendFormat": "write {{device}}"}],
        unit="Bps", fill=3))
    y += 8

    # ---- network ----
    P.append(row("Network", y)); y += 1
    P.append(ts("Throughput", g(0, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'rate(node_network_receive_bytes_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "rx {{device}}"},
         {"refId": "B", "datasource": PROM,
          "expr": f'- rate(node_network_transmit_bytes_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "tx {{device}}"}], unit="Bps", fill=3))
    P.append(ts("Errors & drops", g(12, y, 12, 8),
        [{"refId": "A", "datasource": PROM,
          "expr": f'rate(node_network_receive_errs_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "rx err {{device}}"},
         {"refId": "B", "datasource": PROM,
          "expr": f'rate(node_network_transmit_errs_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "tx err {{device}}"},
         {"refId": "C", "datasource": PROM,
          "expr": f'rate(node_network_receive_drop_total{{{node}, device!~"lo|veth.*|docker.*|br-.*"}}[$__rate_interval])',
          "legendFormat": "rx drop {{device}}"}], unit="pps", fill=0, minv=0))
    y += 8

    links = [
        {"title": "↔ all infra hosts", "type": "dashboards",
         "tags": ["infra", "generated"], "asDropdown": True, "icon": "external link",
         "includeVars": False, "keepTime": True},
    ]
    dash = {
        "uid": uid, "title": name,
        "tags": ["infra", "host", "valura", "generated"],
        "timezone": "browser", "editable": True, "schemaVersion": 42,
        "graphTooltip": 1, "fiscalYearStartMonth": 0, "weekStart": "", "preload": False,
        "refresh": "30s", "time": {"from": "now-3h", "to": "now"},
        "timepicker": {}, "templating": {"list": []},
        "links": links,
        "annotations": {"list": [{"builtIn": 1, "type": "dashboard",
                        "datasource": {"type": "grafana", "uid": "-- Grafana --"},
                        "enable": True, "hide": True, "name": "Annotations & Alerts"}]},
        "panels": P,
    }
    return dash


if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    import os
    for name, cfg in HOSTS.items():
        d = build(name, cfg)
        folder_dir = f"{out}/{cfg['folder']}"
        os.makedirs(folder_dir, exist_ok=True)
        p = f"{folder_dir}/{cfg['uid']}.json"
        json.dump(d, open(p, "w"), indent=2)
        open(p, "a").write("\n")
        print(f"wrote {p}  ({len(d['panels'])} panels)")
