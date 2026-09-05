#!/usr/bin/env python3
"""Poll the Coolify API for every application's current status and push it to
Pushgateway, so Grafana can show a green/red box per service without anyone
having to notice a failed deploy in the Coolify UI themselves.

Coolify's REST API has no deployment-history endpoint that actually returns
data (/api/v1/deployments and /api/v1/deployments/applications/{uuid} both
come back empty - they only ever show a currently in-flight deployment, never
past ones). The closest honest signal for "did the last deploy leave this
healthy" is the application's live container status
(`running:healthy` / `exited:unhealthy` / `restarting:unhealthy` / ...), so
that's what this reports - not a deploy-event log.

Run every 2 minutes via cron on .52 (reaches the Coolify box over the
internal network, pushes to the Pushgateway already running on .52):

    */2 * * * * COOLIFY_TOKEN=... /usr/bin/python3 /path/coolify-deploy-status.py

Security: the /api/v1/applications response carries real secrets per app
(manual_webhook_secret_*, full docker_compose_raw/env) and the /applications
list is ~1.9MB. This script pulls that response into memory, extracts exactly
five scalar fields per app, and discards the rest before anything is written
to disk or pushed anywhere - the webhook secrets and compose bodies never
leave this process.
"""
import json, os, re, sys, time, urllib.request, urllib.error

COOLIFY_URL = os.environ.get("COOLIFY_URL", "http://10.200.1.2:8000")
TOKEN = os.environ.get("COOLIFY_TOKEN")
if not TOKEN:
    sys.exit("Set COOLIFY_TOKEN=<coolify api token> first (never hardcode it here - this file is committed to git).")

PUSHGATEWAY = os.environ.get("PUSHGATEWAY_URL", "http://localhost:9091")
CACHE_FILE = os.environ.get("COOLIFY_ENV_CACHE", "/root/.coolify_env_map_cache.json")
CACHE_TTL = 3600  # project/environment structure barely changes - refresh hourly, not every poll

def api(path):
    req = urllib.request.Request(COOLIFY_URL + path,
        headers={"Authorization": f"Bearer {TOKEN}", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def esc(s):
    return str(s).replace("\\", "\\\\").replace('"', '\\"')

def build_env_map():
    """environment numeric id -> (project_name, environment_name). Two lightweight
    calls per project (list + detail), ~38 projects - no secrets in either."""
    m = {}
    for proj in api("/api/v1/projects"):
        detail = api(f"/api/v1/projects/{proj['uuid']}")
        for env in detail.get("environments", []):
            m[env["id"]] = (proj["name"], env["name"])
    return m

def load_env_map():
    try:
        cached = json.load(open(CACHE_FILE))
        if time.time() - cached["ts"] < CACHE_TTL:
            return {int(k): tuple(v) for k, v in cached["map"].items()}
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        pass
    m = build_env_map()
    try:
        json.dump({"ts": time.time(), "map": {str(k): v for k, v in m.items()}}, open(CACHE_FILE, "w"))
    except OSError:
        pass
    return m

def clean_name(name, uuid):
    # Coolify app names are "<repo>:<branch>-<uuid>" - strip the uuid suffix,
    # it's already its own label.
    return re.sub(re.escape(f"-{uuid}") + "$", "", name)

def main():
    t0 = time.time()
    lines = [
        "# HELP coolify_app_up 1 if the application's container is in the running state, 0 otherwise.",
        "# TYPE coolify_app_up gauge",
        "# HELP coolify_app_healthy 1 if Coolify's healthcheck reports healthy, 0 if unhealthy, -1 if no healthcheck configured.",
        "# TYPE coolify_app_healthy gauge",
        "# HELP coolify_app_last_online_timestamp Unix time Coolify last saw this app's container online.",
        "# TYPE coolify_app_last_online_timestamp gauge",
    ]
    try:
        env_map = load_env_map()
        apps = api("/api/v1/applications")
        for a in apps:
            uuid = a.get("uuid", "")
            name = clean_name(a.get("name", uuid), uuid)
            status = a.get("status") or "unknown"
            env_id = a.get("environment_id")
            project, environment = env_map.get(env_id, ("unknown", "unknown"))
            state, _, health = status.partition(":")
            up = 1 if state == "running" else 0
            healthy = 1 if health == "healthy" else (0 if health == "unhealthy" else -1)
            labels = (f'project="{esc(project)}",environment="{esc(environment)}",'
                      f'app="{esc(name)}",uuid="{esc(uuid)}",status="{esc(status)}"')
            lines.append(f'coolify_app_up{{{labels}}} {up}')
            lines.append(f'coolify_app_healthy{{{labels}}} {healthy}')
            last_online = a.get("last_online_at")
            if last_online:
                try:
                    ts = time.mktime(time.strptime(last_online, "%Y-%m-%d %H:%M:%S"))
                    lines.append(f'coolify_app_last_online_timestamp{{{labels}}} {ts}')
                except ValueError:
                    pass
        lines += [
            "# HELP coolify_poll_success 1 if the last poll of the Coolify API completed without error.",
            "# TYPE coolify_poll_success gauge",
            "coolify_poll_success 1",
            "# HELP coolify_poll_apps_total Number of applications returned by the last successful poll.",
            "# TYPE coolify_poll_apps_total gauge",
            f"coolify_poll_apps_total {len(apps)}",
        ]
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as e:
        lines += [
            "# HELP coolify_poll_success 1 if the last poll of the Coolify API completed without error.",
            "# TYPE coolify_poll_success gauge",
            "coolify_poll_success 0",
        ]
        print(f"poll failed: {e}", file=sys.stderr)

    lines += [
        "# HELP coolify_poll_duration_seconds How long the last poll took.",
        "# TYPE coolify_poll_duration_seconds gauge",
        f"coolify_poll_duration_seconds {time.time() - t0:.3f}",
        "# HELP coolify_last_poll_timestamp_seconds Unix time this poll ran (success or failure) - watch this for staleness if the cron job stops.",
        "# TYPE coolify_last_poll_timestamp_seconds gauge",
        f"coolify_last_poll_timestamp_seconds {time.time():.0f}",
    ]

    body = ("\n".join(lines) + "\n").encode()
    req = urllib.request.Request(f"{PUSHGATEWAY}/metrics/job/coolify-deployments",
                                  data=body, method="PUT")
    try:
        urllib.request.urlopen(req, timeout=10)
    except (urllib.error.URLError, urllib.error.HTTPError) as e:
        sys.exit(f"push to pushgateway failed: {e}")

if __name__ == "__main__":
    main()
