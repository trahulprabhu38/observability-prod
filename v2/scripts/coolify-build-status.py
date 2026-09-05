#!/usr/bin/env python3
"""Poll Coolify's own deployment-history table for the last 3 builds of every
application and push pass/fail status to Pushgateway - the piece
coolify-deploy-status.py can't give you: that script reports whether a
container is *currently* up/healthy, which stays green even when the most
recent *build* failed and Coolify just kept the previous container running.
This answers "did the build itself fail", independently of current uptime.

Coolify's API has no working deployment-history endpoint (see
coolify-deploy-status.py's docstring - confirmed empty on two different
routes). The data genuinely exists, just only in Coolify's own Postgres
table (`application_deployment_queues`), which the API never surfaces. This
reads it directly with a read-only SQL query via `docker exec`.

Must run ON the Coolify box (10.200.1.2) - `coolify-db`'s Postgres port
isn't published to the host network, only reachable via `docker exec`
locally. Pushes cross-network to the Pushgateway on .52 (confirmed reachable
both directions).

Security: `application_deployment_queues.logs` holds full build output,
which can include anything a build script printed (env vars, tokens people
echoed by accident, etc.) - the query below never selects that column, or
`configuration_snapshot`/`configuration_diff` (raw compose+env snapshots).
Only status, timestamps, and the git commit SHA are pulled per build.

Run every 5 minutes via cron on 10.200.1.2:
    */5 * * * * /usr/bin/python3 /path/coolify-build-status.py
"""
import re, subprocess, sys, time, urllib.request, urllib.error

PUSHGATEWAY = "http://10.200.2.52:9091"
SEP = "\x01"

QUERY = f"""
WITH ranked AS (
  SELECT application_id, status, created_at, finished_at, commit,
         ROW_NUMBER() OVER (PARTITION BY application_id ORDER BY created_at DESC) AS rn
  FROM application_deployment_queues
)
SELECT a.uuid, a.name, p.name AS project, e.name AS environment,
       r.status, r.created_at, r.finished_at, r.commit, r.rn
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

def main():
    t0 = time.time()
    lines = [
        "# HELP coolify_build_success 1 if this build finished cleanly, 0 if it failed, -1 for any other outcome (cancelled, etc.).",
        "# TYPE coolify_build_success gauge",
        "# HELP coolify_build_timestamp_seconds Unix time this build started.",
        "# TYPE coolify_build_timestamp_seconds gauge",
        "# HELP coolify_build_duration_seconds How long this build took, if it finished.",
        "# TYPE coolify_build_duration_seconds gauge",
    ]
    n_rows = 0
    try:
        proc = subprocess.run(
            ["docker", "exec", "coolify-db", "psql", "-U", "coolify", "-d", "coolify",
             "-At", "-F", SEP, "-c", QUERY],
            capture_output=True, text=True, timeout=30, check=True)
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            uuid, name, project, environment, status, created_at, finished_at, commit, rank = line.split(SEP)
            n_rows += 1
            name = clean_name(name, uuid)
            success = 1 if status == "finished" else (0 if status == "failed" else -1)
            labels = (f'project="{esc(project)}",environment="{esc(environment)}",'
                      f'app="{esc(name)}",uuid="{esc(uuid)}",rank="{rank}",'
                      f'status="{esc(status)}",commit="{esc(commit[:12])}"')
            lines.append(f'coolify_build_success{{{labels}}} {success}')
            start = to_epoch(created_at)
            if start:
                lines.append(f'coolify_build_timestamp_seconds{{{labels}}} {start:.0f}')
                end = to_epoch(finished_at)
                if end:
                    lines.append(f'coolify_build_duration_seconds{{{labels}}} {end - start:.0f}')
        lines += [
            "# HELP coolify_build_poll_success 1 if the last poll of the deployment-history table completed without error.",
            "# TYPE coolify_build_poll_success gauge",
            "coolify_build_poll_success 1",
            "# HELP coolify_build_poll_rows_total Number of (app, rank) build records in the last successful poll.",
            "# TYPE coolify_build_poll_rows_total gauge",
            f"coolify_build_poll_rows_total {n_rows}",
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
        "# HELP coolify_build_last_poll_timestamp_seconds Unix time this poll ran (success or failure) - watch this for staleness if the cron job stops.",
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
