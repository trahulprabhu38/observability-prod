#!/usr/bin/env bash
# Pull every dashboard out of the prod Grafana instance and write each one as a
# bare dashboard JSON under grafana/dashboards/<folder>/<slug>.json.
#
# These are the source of truth; the v2 stack imports re-pointed copies of them
# (see ../../v2/grafana/provisioning/dashboards/).
#
# Usage:
#   GRAFANA_URL=https://grafana-infra.valura.co.in \
#   GRAFANA_USER=valuraadmin GRAFANA_PASS='...' \
#   ./scripts/fetch-grafana-dashboards.sh
#
# A Grafana API token works too: set GRAFANA_TOKEN instead of USER/PASS.
set -euo pipefail

GRAFANA_URL="${GRAFANA_URL:-https://grafana-infra.valura.co.in}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/grafana/dashboards"
mkdir -p "$OUT"

if [[ -n "${GRAFANA_TOKEN:-}" ]]; then
  AUTH=(-H "Authorization: Bearer ${GRAFANA_TOKEN}")
else
  : "${GRAFANA_USER:?set GRAFANA_USER or GRAFANA_TOKEN}"
  : "${GRAFANA_PASS:?set GRAFANA_PASS or GRAFANA_TOKEN}"
  CJ="$(mktemp)"; trap 'rm -f "$CJ"' EXIT
  curl -fsS -c "$CJ" -X POST "$GRAFANA_URL/login" \
    -H 'Content-Type: application/json' \
    -d "$(python3 -c 'import json,os;print(json.dumps({"user":os.environ["GRAFANA_USER"],"password":os.environ["GRAFANA_PASS"]}))')" \
    >/dev/null
  AUTH=(-b "$CJ")
fi

api() { curl -fsS "${AUTH[@]}" "$GRAFANA_URL$1"; }

echo ">> listing dashboards on $GRAFANA_URL"
api "/api/search?type=dash-db&limit=1000" | \
  python3 -c "import json,sys;[print(r['uid'], r.get('folderTitle') or 'General') for r in json.load(sys.stdin)]" | \
while read -r uid folder; do
  fslug="$(printf '%s' "$folder" | tr '[:upper:]' '[:lower:]' | tr -cs 'a-z0-9' '-' | sed 's/^-//;s/-$//')"
  mkdir -p "$OUT/$fslug"
  api "/api/dashboards/uid/$uid" | OUT="$OUT" FSLUG="$fslug" python3 -c "
import json, os, re, sys
d = json.load(sys.stdin)['dashboard']
d['id'] = None
d.pop('version', None)
slug = re.sub(r'[^a-z0-9]+', '-', d.get('title', 'dash').lower()).strip('-')
path = os.path.join(os.environ['OUT'], os.environ['FSLUG'], slug + '.json')
open(path, 'w').write(json.dumps(d, indent=2, ensure_ascii=False) + '\n')
print('  saved', os.path.relpath(path, os.environ['OUT']))
"
done

echo "Done -> $OUT"
