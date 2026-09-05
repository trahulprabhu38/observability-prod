#!/usr/bin/env python3
"""Poll Coolify's own deployment-history table for the last 3 builds of every
application: push pass/fail status to Pushgateway, and ship each build's full
log to Loki so a failed build can be read straight from the Grafana
dashboard.

coolify-deploy-status.py reports whether a container is *currently* up;
this reports whether the last few *builds* passed, and now carries the log
for each so you don't have to open Coolify to see why one failed.

Coolify's API has no working deployment-history endpoint (confirmed empty on
two routes) - the data only lives in Coolify's Postgres table
`application_deployment_queues`. `coolify-db`'s port isn't published to the
host, so this runs ON the Coolify box (10.200.1.2) via `docker exec` and
pushes cross-network to .52 (Pushgateway :9091 and Loki :3100, both
confirmed reachable).

Build logs: `application_deployment_queues.logs` is a JSON array of
{output,timestamp,type,hidden,...} entries. Each build's log is pushed to
Loki ONCE (tracked in a state file), as stream
`{job="coolify_build_logs", project, environment, app}` with per-line
structured metadata `deployment_uuid` / `status` / `commit` / `stream`.
Stream labels stay low-cardinality (~one per app); the dashboard filters to
a single build by `| deployment_uuid="..."`. Loki keeps 14 days (its
config), so old build logs age out on their own. This does mean build logs -
which can contain whatever a build script printed - are now readable by
anyone with access to the dashboard's folder; that's the point of the
feature, but worth knowing.

Run every 5 minutes via cron on 10.200.1.2:
    */5 * * * * /usr/bin/python3 /path/coolify-build-status.py
"""
import json, os, re, subprocess, sys, time, urllib.request, urllib.error

PUSHGATEWAY = "http://10.200.2.52:9091"
LOKI = "http://10.200.2.52:3100"
SEP = "\x01"
STATE_FILE = os.environ.get("COOLIFY_BUILD_LOG_STATE", "/root/.coolify_build_logs_pushed.json")
STATE_TTL = 20 * 86400          # forget a pushed-uuid record after 20 days (Loki keeps 14)
MAX_LINES_PER_BUILD = 5000      # truncate pathologically long build logs
MAX_APPS_PER_RUN = 80           # ship up to this many apps' logs per run (x3 builds)

STATUS_QUERY = f"""
WITH ranked AS (
  SELECT application_id, deployment_uuid, status, created_at, finished_at, commit,
         ROW_NUMBER() OVER (PARTITION BY application_id ORDER BY created_at DESC) AS rn
  FROM application_deployment_queues
)
SELECT a.uuid, a.name, p.name AS project, e.name AS environment,
       r.status, r.created_at, r.finished_at, r.commit, r.rn, r.deployment_uuid
FROM ranked r
JOIN applications a ON a.id::varchar = r.application_id
JOIN environments e ON e.id = a.environment_id
JOIN projects p ON p.id = e.project_id
WHERE r.rn <= 3
ORDER BY a.id, r.rn;
"""

def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')

def clean_name(name, uuid):
    return re.sub(re.escape(f"-{uuid}") + "$", "", name)

def to_epoch(ts):
    if not ts:
        return None
    try:
        return time.mktime(time.strptime(ts, "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return None

def psql(query):
    return subprocess.run(
        ["docker", "exec", "coolify-db", "psql", "-U", "coolify", "-d", "coolify",
         "-At", "-F", SEP, "-c", query],
        capture_output=True, text=True, timeout=60, check=True).stdout


# ---------------------------------------------------------------- build logs ---
def iso_to_ns(ts, fallback_epoch):
    if ts:
        try:
            t = ts.replace("Z", "+0000")
            # 2026-09-05T15:46:23.679151+0000
            base, _, frac = t.partition(".")
            st = time.strptime(base, "%Y-%m-%dT%H:%M:%S")
            secs = int(time.mktime(st) - time.timezone)
            micros = int((frac[:6].split("+")[0] or "0").ljust(6, "0")) if frac else 0
            return secs * 1_000_000_000 + micros * 1000
        except (ValueError, IndexError):
            pass
    return int(fallback_epoch * 1_000_000_000)

def push_one_build_log(uuid, project, environment, app, status, commit, created_at, raw_logs):
    try:
        entries = json.loads(raw_logs) if raw_logs else []
    except (json.JSONDecodeError, TypeError):
        return False
    if not isinstance(entries, list) or not entries:
        return False

    entries = [e for e in entries if isinstance(e, dict) and not e.get("hidden")]
    entries.sort(key=lambda e: (e.get("batch", 0), e.get("order", 0)))
    fallback = to_epoch(created_at) or time.time()

    values, last_ns = [], 0
    for e in entries[:MAX_LINES_PER_BUILD]:
        text = str(e.get("output", "")).rstrip("\n")
        if not text:
            continue
        ns = iso_to_ns(e.get("timestamp"), fallback)
        if ns <= last_ns:                      # keep strictly increasing within the stream slice
            ns = last_ns + 1000
        last_ns = ns
        values.append([str(ns), text, {
            "deployment_uuid": uuid, "status": status,
            "commit": (commit or "")[:12], "stream": e.get("type", "stdout"),
        }])
    if len(entries) > MAX_LINES_PER_BUILD:
        values.append([str(last_ns + 1000),
                       f"... build log truncated at {MAX_LINES_PER_BUILD} lines ...",
                       {"deployment_uuid": uuid, "status": status, "commit": (commit or "")[:12], "stream": "meta"}])
    if not values:
        return False

    payload = json.dumps({"streams": [{
        "stream": {"job": "coolify_build_logs", "project": project,
                   "environment": environment, "app": app},
        "values": values,
    }]}).encode()
    req = urllib.request.Request(f"{LOKI}/loki/api/v1/push", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        urllib.request.urlopen(req, timeout=20)
        return "ok"
    except urllib.error.HTTPError as ex:
        # 400 = "entry too far behind": build older than Loki's reject window
        # (14d retention here). Record it so we stop retrying, but don't count
        # it as shipped.
        print(f"loki push {uuid}: HTTP {ex.code} {ex.read()[:160]!r}", file=sys.stderr)
        return "skip" if ex.code == 400 else "retry"
    except urllib.error.URLError as ex:
        print(f"loki push {uuid}: {ex}", file=sys.stderr)
        return "retry"

def ship_build_logs(builds):
    """builds: list of dicts with keys uuid/project/environment/app/status/commit/created_at."""
    try:
        state = json.load(open(STATE_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    now = time.time()
    state = {k: v for k, v in state.items() if now - v < STATE_TTL}

    # Group unshipped builds by app. Prioritise apps by their most RECENT build
    # (so a fresh failure ships this run, not after the whole backfill), but
    # within an app push its builds OLDEST first - several builds of one app
    # share a Loki stream and Loki rejects an entry older than what the stream
    # has already taken.
    groups = {}
    for b in builds:
        if b["uuid"] not in state:
            groups.setdefault((b["project"], b["app"]), []).append(b)
    apps_by_recency = sorted(groups.items(),
                             key=lambda kv: max(x["created_at"] or "" for x in kv[1]),
                             reverse=True)[:MAX_APPS_PER_RUN]
    todo = []
    for _, blds in apps_by_recency:
        todo.extend(sorted(blds, key=lambda x: x["created_at"] or ""))

    shipped = 0
    if todo:
        uuid_list = ",".join("'" + b["uuid"].replace("'", "") + "'" for b in todo)
        # json_agg -> one JSON value, no line/field splitting to get wrong on
        # multi-KB log blobs. `logs` comes back as its raw text for us to parse.
        blob = psql(f"SELECT coalesce(json_agg(json_build_object('u', deployment_uuid, "
                    f"'l', logs)), '[]') FROM application_deployment_queues "
                    f"WHERE deployment_uuid IN ({uuid_list});").strip()
        try:
            logs_by_uuid = {r["u"]: r["l"] for r in json.loads(blob)}
        except json.JSONDecodeError:
            logs_by_uuid = {}
        skip_app = None
        for b in todo:
            if (b["project"], b["app"]) == skip_app:
                continue                       # a push failed earlier in this app's group
            raw = logs_by_uuid.get(b["uuid"])
            if raw is None:
                continue
            result = push_one_build_log(b["uuid"], b["project"], b["environment"], b["app"],
                                        b["status"], b["commit"], b["created_at"], raw)
            if result in ("ok", "skip"):
                state[b["uuid"]] = now
            if result == "ok":
                shipped += 1
            if result == "retry":
                # leave this app's remaining (newer) builds for next run so the
                # stream stays in order
                skip_app = (b["project"], b["app"])
    try:
        json.dump(state, open(STATE_FILE, "w"))
    except OSError:
        pass
    return shipped


# --------------------------------------------------------------------- main ---
def main():
    t0 = time.time()
    lines = [
        "# HELP coolify_build_success 1 if this build finished cleanly, 0 if it failed, -1 for any other outcome.",
        "# TYPE coolify_build_success gauge",
        "# HELP coolify_build_timestamp_seconds Unix time this build started.",
        "# TYPE coolify_build_timestamp_seconds gauge",
        "# HELP coolify_build_duration_seconds How long this build took, if it finished.",
        "# TYPE coolify_build_duration_seconds gauge",
    ]
    n_rows, n_logs_new = 0, 0
    try:
        out = psql(STATUS_QUERY)
        builds = []
        for line in out.splitlines():
            if not line.strip():
                continue
            (uuid, name, project, environment, status, created_at,
             finished_at, commit, rank, deployment_uuid) = line.split(SEP)
            n_rows += 1
            name = clean_name(name, uuid)
            success = 1 if status == "finished" else (0 if status == "failed" else -1)
            labels = (f'project="{esc(project)}",environment="{esc(environment)}",'
                      f'app="{esc(name)}",uuid="{esc(uuid)}",rank="{rank}",'
                      f'status="{esc(status)}",commit="{esc(commit[:12])}",'
                      f'deployment_uuid="{esc(deployment_uuid)}"')
            lines.append(f'coolify_build_success{{{labels}}} {success}')
            start = to_epoch(created_at)
            if start:
                lines.append(f'coolify_build_timestamp_seconds{{{labels}}} {start:.0f}')
                end = to_epoch(finished_at)
                if end:
                    lines.append(f'coolify_build_duration_seconds{{{labels}}} {end - start:.0f}')
            builds.append({"uuid": deployment_uuid, "project": project, "environment": environment,
                           "app": name, "status": status, "commit": commit, "created_at": created_at})

        n_logs_new = ship_build_logs(builds)

        lines += [
            "# HELP coolify_build_poll_success 1 if the last poll of the deployment-history table completed without error.",
            "# TYPE coolify_build_poll_success gauge",
            "coolify_build_poll_success 1",
            "# HELP coolify_build_poll_rows_total Number of (app, rank) build records in the last successful poll.",
            "# TYPE coolify_build_poll_rows_total gauge",
            f"coolify_build_poll_rows_total {n_rows}",
            "# HELP coolify_build_logs_shipped_total Build logs newly shipped to Loki this run.",
            "# TYPE coolify_build_logs_shipped_total gauge",
            f"coolify_build_logs_shipped_total {n_logs_new}",
        ]
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as e:
        lines += [
            "# HELP coolify_build_poll_success 1 if the last poll of the deployment-history table completed without error.",
            "# TYPE coolify_build_poll_success gauge",
            "coolify_build_poll_success 0",
        ]
        print(f"poll failed: {e}", file=sys.stderr)

    lines += [
        "# HELP coolify_build_poll_duration_seconds How long the last poll took.",
        "# TYPE coolify_build_poll_duration_seconds gauge",
        f"coolify_build_poll_duration_seconds {time.time() - t0:.3f}",
        "# HELP coolify_build_last_poll_timestamp_seconds Unix time this poll ran (success or failure).",
        "# TYPE coolify_build_last_poll_timestamp_seconds gauge",
        f"coolify_build_last_poll_timestamp_seconds {time.time():.0f}",
    ]

    body = ("\n".join(lines) + "\n").encode()
    req = urllib.request.Request(f"{PUSHGATEWAY}/metrics/job/coolify-builds",
                                  data=body, method="PUT")
    try:
        urllib.request.urlopen(req, timeout=10)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        sys.exit(f"push to pushgateway failed: {e}")

if __name__ == "__main__":
    main()
