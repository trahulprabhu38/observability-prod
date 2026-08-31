#!/usr/bin/env bash
# ============================================================================
#  cAdvisor fleet rollout - one container per box, published on :8085.
#  Idempotent: safe to re-run (removes any existing 'cadvisor' container first).
#  Nothing else on the box is touched.
#
#  Usage:
#     ./cadvisor-rollout.sh                # roll out to every box in the list
#     ./cadvisor-rollout.sh 10.200.2.51    # just one box
#     SSH_USER=ubuntu ./cadvisor-rollout.sh
#
#  After rollout, targets are scraped by the 'cadvisor-fleet' job in
#  prometheus/prometheus.yml   (verify: promtool check config, then reload).
# ============================================================================
set -euo pipefail

IMAGE="gcr.io/cadvisor/cadvisor:v0.49.1"
PORT="8085"
SSH_USER="${SSH_USER:-root}"
SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new"

# box            ip
BOXES=(
  "valura-dev      10.200.2.51"
  "observability   10.200.2.52"
  "prod-uae        10.200.2.54"
  "uae-staging     10.200.2.56"
  "valura-ind-stg  10.200.2.57"
  "dubai           86.106.26.45"
  # "edge          <EDGE_BOX_IP>"
)

run_cmd='
  docker rm -f cadvisor >/dev/null 2>&1 || true
  docker run -d --name cadvisor --restart unless-stopped -p '"$PORT"':8080 \
    -v /:/rootfs:ro -v /var/run:/var/run:ro -v /sys:/sys:ro \
    -v /var/lib/docker/:/var/lib/docker:ro -v /dev/disk/:/dev/disk:ro \
    --privileged --device /dev/kmsg '"$IMAGE"'
  sleep 2
  curl -sf "http://localhost:'"$PORT"'/healthz" && echo " OK" || { echo " HEALTHCHECK FAILED"; exit 1; }
'

targets=()
if [[ $# -gt 0 ]]; then
  targets=("$@")
else
  for row in "${BOXES[@]}"; do targets+=("$(echo "$row" | awk '{print $2}')"); done
fi

for ip in "${targets[@]}"; do
  echo "=== $ip ==="
  if ssh $SSH_OPTS "${SSH_USER}@${ip}" "$run_cmd"; then
    echo "--- $ip done"
  else
    echo "!!! $ip FAILED (skipping)"
  fi
  echo
done
