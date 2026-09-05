#!/usr/bin/env bash
# Onboard one person into the Grafana RBAC system: creates a local account,
# sets their org role (lead=Editor, dev=Viewer), and drops them into their
# project team + access-classification team.
#
# Usage:
#   ./grafana-add-user.sh <email> "<full name>" <password> <team> <lead|dev> <prod|general>
#
#   <team>   one of: UAE | IND | Partner-Apps
#   lead     -> org role Editor      dev     -> org role Viewer
#   prod     -> also sees Production folder (+ everything general sees)
#   general  -> sees everything except Production
#
# Example:
#   ./grafana-add-user.sh priya@company.com "Priya Sharma" 'TempPass123!' UAE lead prod
set -euo pipefail

EMAIL="$1"; NAME="$2"; PASS="$3"; TEAM="$4"; ROLE="$5"; ACCESS="$6"

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
if [ -z "${GRAFANA_AUTH:-}" ]; then
  echo "Set GRAFANA_AUTH=<admin-login>:<admin-password> first (never hardcode it here - this file is committed to git)." >&2
  exit 1
fi

case "$ROLE" in
  lead) ORG_ROLE="Editor" ;;
  dev)  ORG_ROLE="Viewer" ;;
  *) echo "role must be 'lead' or 'dev'" >&2; exit 1 ;;
esac

case "$ACCESS" in
  prod)    ACCESS_TEAM="Prod-View" ;;
  general) ACCESS_TEAM="General-View" ;;
  *) echo "access must be 'prod' or 'general'" >&2; exit 1 ;;
esac

api() { curl -s -u "$GRAFANA_AUTH" -H "Content-Type: application/json" "$@"; }

echo ">> creating user $EMAIL"
CREATE_RESP=$(api -X POST "$GRAFANA_URL/api/admin/users" -d "{\"name\":\"$NAME\",\"email\":\"$EMAIL\",\"login\":\"$EMAIL\",\"password\":\"$PASS\",\"OrgId\":1}")
USER_ID=$(echo "$CREATE_RESP" | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("id") or d.get("message"))')
if ! [[ "$USER_ID" =~ ^[0-9]+$ ]]; then
  echo "!! failed to create user: $CREATE_RESP" >&2
  exit 1
fi
echo "   user id: $USER_ID"

echo ">> setting org role: $ORG_ROLE"
api -X PATCH "$GRAFANA_URL/api/org/users/$USER_ID" -d "{\"role\":\"$ORG_ROLE\"}" >/dev/null

team_id() { api "$GRAFANA_URL/api/teams/search?name=$1" | python3 -c 'import json,sys; print(json.load(sys.stdin)["teams"][0]["id"])'; }

for T in "$TEAM" "$ACCESS_TEAM"; do
  TID=$(team_id "$T")
  echo ">> adding to team: $T (id $TID)"
  api -X POST "$GRAFANA_URL/api/teams/$TID/members" -d "{\"userId\":$USER_ID}" >/dev/null
done

echo "done: $EMAIL is $ORG_ROLE, in teams [$TEAM, $ACCESS_TEAM]"
