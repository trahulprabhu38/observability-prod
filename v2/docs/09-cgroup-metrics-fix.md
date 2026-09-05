# 09 - Per-container metrics without cAdvisor

Two boxes (`10.200.2.57` IND staging, `10.200.2.54` UAE production) run
cAdvisor v0.52.1 that registers its Docker factory cleanly but returns **zero**
per-container series - `container_last_seen` shows only the root cgroup and
every systemd unit, never a single `docker-<id>.scope`, even though those
cgroup directories exist on disk and `docker inspect`/Alloy's own Docker
discovery work fine on the same host. Full dead-end list is in
`../stg-box/README.md` (six fixes tried, including the one that resolved the
identical symptom on `.51`). Root cause not identified; looks specific to this
cAdvisor build on these hosts (a real VM and, separately, an LXC that both
differ from `.51`'s working LXC in some undetermined way).

## The fix: read cgroup v2 files directly from the host

cAdvisor's problem is specifically *cAdvisor-running-as-a-Docker-container*
losing visibility into sibling containers' cgroups. The same files are
readable with zero issues from **outside** any container - i.e. a script
running directly on the box (a cron job, not a Docker container):

```
/sys/fs/cgroup/system.slice/docker-<full-container-id>.scope/
  cpu.stat        -> usage_usec              (cumulative CPU time)
  memory.current  -> current memory bytes
  memory.stat     -> inactive_file           (subtract for "working set")
  memory.max      -> configured limit, or the literal string "max"
  memory.events   -> oom_kill                (cumulative OOM kill count)
```

`scripts/coolify-cgroup-metrics.sh` walks `docker ps`, resolves each
container's Coolify labels via `docker inspect`, reads the files above, and
writes Prometheus text-format output to
`/root/node-exporter/textfile/coolify_cgroup_metrics.prom` - picked up by
node-exporter's textfile collector and scraped like any other node-exporter
metric.

**Metric and label names deliberately match cAdvisor's own**
(`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`,
`container_spec_memory_limit_bytes`, `container_start_time_seconds`,
`container_last_seen`, `container_oom_events_total`,
`container_label_coolify_projectName`, `container_label_coolify_resourceName`)
so the dashboards need zero changes to consume either source - a box either
has real cAdvisor series or these textfile ones, never both, and every panel
just works.

## Deploy on a new box that hits this

```bash
# node-exporter needs the textfile collector - see v2/stg-box/*/node-exporter/docker-compose.yml
# for the exact compose (adds --collector.textfile.directory=/textfile + a
# volume mount at /root/node-exporter/textfile, NOT under the read-only /host
# bind - node-exporter can't create a mountpoint on a ro filesystem).

scp scripts/coolify-cgroup-metrics.sh root@<box>:/usr/local/bin/
ssh root@<box> 'chmod +x /usr/local/bin/coolify-cgroup-metrics.sh
  mkdir -p /root/node-exporter/textfile
  /usr/local/bin/coolify-cgroup-metrics.sh   # run once, sanity-check the output
  echo "* * * * * /usr/local/bin/coolify-cgroup-metrics.sh >/dev/null 2>&1" | crontab -'
```

## What it does NOT cover

- **Per-container network I/O** (RX/TX, errors, drops). Cgroup v2 has no
  per-container network accounting file the way it does for CPU/memory -
  that needs reading `/proc/<pid>/net/dev` for a process inside the
  container's network namespace, meaningfully more code. The "network"
  section's per-service panels stay empty on these two boxes; it's already
  the lowest-priority row on every dashboard.
- Anything cAdvisor-only like `container_fs_*` (disk I/O) - not currently
  used by any dashboard panel, so not implemented here.

## Verify it's working

```bash
ssh root@<box> 'crontab -l | grep coolify-cgroup-metrics'
curl -s http://<box>:9100/metrics | grep -c coolify_projectName    # > 0
curl -s http://<box>:9100/metrics | grep node_textfile_scrape_error  # must read 0
```
