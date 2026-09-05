#!/usr/bin/env bash
# Per-container CPU/memory metrics read straight from cgroup v2, for boxes
# where cAdvisor cannot see per-container cgroups from inside its own Docker
# container (confirmed: registers its Docker factory cleanly, returns zero
# containers - a nested-cgroup-namespace quirk on this Docker/kernel combo).
# The SAME cgroup files are readable from the host (outside any container),
# which is what this runs as - a cron job, not a container.
#
# Metric names/labels match cAdvisor's own so the existing dashboards work
# unmodified: container_cpu_usage_seconds_total, container_memory_working_set_bytes,
# container_spec_memory_limit_bytes, container_start_time_seconds, container_last_seen.
# Consumed by node-exporter's textfile collector.
set -euo pipefail

OUT=/root/node-exporter/textfile/coolify_cgroup_metrics.prom
TMP="$(mktemp)"
NOW=$(date +%s)

esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

{
  echo "# HELP container_cpu_usage_seconds_total Cumulative CPU time, read from cgroup v2 (cAdvisor can't see per-container cgroups on this host)."
  echo "# TYPE container_cpu_usage_seconds_total counter"
  echo "# HELP container_memory_working_set_bytes Current memory usage minus inactive file cache, read from cgroup v2."
  echo "# TYPE container_memory_working_set_bytes gauge"
  echo "# HELP container_spec_memory_limit_bytes Configured memory limit, read from cgroup v2."
  echo "# TYPE container_spec_memory_limit_bytes gauge"
  echo "# HELP container_start_time_seconds Unix time the container last started."
  echo "# TYPE container_start_time_seconds gauge"
  echo "# HELP container_last_seen Last time this exporter saw the container running."
  echo "# TYPE container_last_seen gauge"
  echo "# HELP container_oom_events_total Cumulative OOM kills, read from cgroup v2 memory.events."
  echo "# TYPE container_oom_events_total counter"

  for id in $(docker ps -q); do
    full_id=$(docker inspect -f '{{.Id}}' "$id" 2>/dev/null) || continue
    name=$(docker inspect -f '{{.Name}}' "$id" 2>/dev/null | sed 's#^/##')
    proj=$(docker inspect -f '{{index .Config.Labels "coolify.projectName"}}' "$id" 2>/dev/null || true)
    res=$(docker inspect -f '{{index .Config.Labels "coolify.resourceName"}}' "$id" 2>/dev/null || true)
    envn=$(docker inspect -f '{{index .Config.Labels "coolify.environmentName"}}' "$id" 2>/dev/null || true)
    [ -z "$proj" ] && continue          # only coolify-managed containers
    [ -z "$res" ] && res="$name"

    CG="/sys/fs/cgroup/system.slice/docker-${full_id}.scope"
    [ -d "$CG" ] || continue

    labels="name=\"$(esc "$name")\",container_label_coolify_projectName=\"$(esc "$proj")\",container_label_coolify_resourceName=\"$(esc "$res")\",container_label_coolify_environmentName=\"$(esc "${envn:-}")\""

    usage_usec=$(awk '/^usage_usec/ {print $2}' "$CG/cpu.stat" 2>/dev/null || echo 0)
    cpu_sec=$(awk -v u="${usage_usec:-0}" 'BEGIN{printf "%.6f", u/1000000}')
    echo "container_cpu_usage_seconds_total{$labels} $cpu_sec"

    mem_current=$(cat "$CG/memory.current" 2>/dev/null || echo 0)
    inactive_file=$(awk '/^inactive_file/ {print $2}' "$CG/memory.stat" 2>/dev/null || echo 0)
    working_set=$(( ${mem_current:-0} - ${inactive_file:-0} ))
    [ "$working_set" -lt 0 ] && working_set=0
    echo "container_memory_working_set_bytes{$labels} $working_set"

    mem_max=$(cat "$CG/memory.max" 2>/dev/null || echo max)
    if [ "$mem_max" != "max" ]; then
      echo "container_spec_memory_limit_bytes{$labels} $mem_max"
    fi

    started_at=$(docker inspect -f '{{.State.StartedAt}}' "$id" 2>/dev/null || true)
    start_epoch=$(date -d "$started_at" +%s 2>/dev/null || echo "$NOW")
    echo "container_start_time_seconds{$labels} $start_epoch"

    echo "container_last_seen{$labels} $NOW"

    oom_kill=$(awk '/^oom_kill/ {print $2}' "$CG/memory.events" 2>/dev/null || echo 0)
    echo "container_oom_events_total{$labels} ${oom_kill:-0}"
  done
} > "$TMP"

chmod 0644 "$TMP"
mv "$TMP" "$OUT"
