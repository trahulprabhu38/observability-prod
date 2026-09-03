#!/usr/bin/env bash
# Download community dashboards from grafana.com into the provisioning folder and
# rewrite their datasource placeholders so they load without manual input.
#
#   ./scripts/fetch-dashboards.sh
#   make reload not needed - the provisioner picks new files up within 30s.
#
# Add/remove IDs in the list below. Find more at https://grafana.com/grafana/dashboards/
set -euo pipefail

OUT="$(cd "$(dirname "$0")/.." && pwd)/grafana/provisioning/dashboards/json"
mkdir -p "$OUT"

# id : filename : short description   (always fetches the LATEST revision)
DASHBOARDS=(
  "1860:node-exporter-full.json:Node Exporter Full (host/LXC metrics)"
  "19792:cadvisor.json:cAdvisor / container metrics"
  "13639:loki-logs.json:Loki stack / log ingestion"
  "15983:otel-collector.json:OpenTelemetry Collector health"
)

for entry in "${DASHBOARDS[@]}"; do
  IFS=':' read -r id file desc <<< "$entry"
  echo ">> $desc  (grafana.com/grafana/dashboards/$id)"
  # look up the latest revision, then download it
  rev="$(curl -fsSL "https://grafana.com/api/dashboards/${id}" | \
         grep -o '"revision":[0-9]*' | head -1 | grep -o '[0-9]*')"
  rev="${rev:-1}"
  url="https://grafana.com/api/dashboards/${id}/revisions/${rev}/download"
  tmp="$(mktemp)"
  curl -fsSL "$url" -o "$tmp"
  # Replace the ${DS_...} datasource variables with our fixed UIDs so provisioning
  # doesn't prompt. Covers the common Prometheus/Loki placeholder names.
  sed -E \
    -e 's/\$\{DS_PROMETHEUS\}/prometheus/g' \
    -e 's/\$\{DS_PROMETHEUS-1\}/prometheus/g' \
    -e 's/\$\{DS_LOKI\}/loki/g' \
    -e 's/"datasource":\s*"Prometheus"/"datasource": {"type":"prometheus","uid":"prometheus"}/g' \
    "$tmp" > "$OUT/$file"
  rm -f "$tmp"
done

echo
echo "Wrote to $OUT"
echo "If a panel shows 'datasource not found', open the dashboard settings in"
echo "Grafana and set the datasource to Prometheus/Loki once, then Save."
