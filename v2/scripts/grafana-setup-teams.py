#!/usr/bin/env python3
# One-time setup: creates the 5 RBAC teams (UAE/IND/Partner-Apps project
# teams + Prod-View/General-View access teams) and grants their folder
# permissions (non-prod <- General-View+Prod-View, production <- Prod-View).
# Idempotent - safe to re-run, looks up existing teams instead of erroring.
# See docs/10-rbac-teams-access.md for the full RBAC model.
import json, urllib.request, base64

BASE = "http://localhost:3000"
AUTH = "Basic " + base64.b64encode(b"admin:admin123").decode()

def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method)
    r.add_header("Authorization", AUTH)
    r.add_header("Content-Type", "application/json")
    try:
        return json.load(urllib.request.urlopen(r, timeout=15))
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"__error__": e.code, "__body__": body}

# 1. Project teams (one per squad, mixed leads+devs)
project_teams = ["UAE", "IND", "Partner-Apps"]
# 2. Access-classification teams (cross-cutting)
access_teams = ["Prod-View", "General-View"]

team_ids = {}
for name in project_teams + access_teams:
    r = call("POST", "/api/teams", {"name": name})
    if "__error__" in r:
        if "already exists" in r.get("__body__", ""):
            # look it up
            search = call("GET", f"/api/teams/search?name={name}")
            team_ids[name] = search["teams"][0]["id"]
            print(f"exists: {name} -> id {team_ids[name]}")
        else:
            print(f"ERROR creating {name}: {r}")
    else:
        team_ids[name] = r["teamId"]
        print(f"created: {name} -> id {r['teamId']}")

# 3. Folders
folders = call("GET", "/api/folders")
folder_uid = {f["title"]: f["uid"] for f in folders}
print("folders:", folder_uid)

# 4. Folder permissions
# General-View -> non-prod: View
# Prod-View    -> non-prod: View  AND production: View   (superset)
def set_perm(folder_title, team_name, permission):
    uid = folder_uid[folder_title]
    tid = team_ids[team_name]
    existing = call("GET", f"/api/folders/{uid}/permissions")
    items = [p for p in existing if p.get("teamId") or p.get("role") == "Admin" and p.get("userId") is None]
    # keep existing non-team basic/inherited entries, drop old grant for this team if present, add new
    new_items = []
    for p in existing:
        if p.get("teamId") == tid:
            continue
        # keep entries that aren't editable "inherited" markers oddly shaped; the API wants userId/teamId/builtInRole + permission
        entry = {}
        if p.get("teamId"): entry = {"teamId": p["teamId"], "permission": p["permission"]}
        elif p.get("userId"): entry = {"userId": p["userId"], "permission": p["permission"]}
        elif p.get("builtInRole"): entry = {"builtInRole": p["builtInRole"], "permission": p["permission"]}
        if entry: new_items.append(entry)
    new_items.append({"teamId": tid, "permission": permission})
    res = call("POST", f"/api/folders/{uid}/permissions", {"items": new_items})
    print(f"  {folder_title} + {team_name} (perm={permission}):", res if "__error__" in res else "ok")

set_perm("non-prod", "General-View", 1)   # 1 = View
set_perm("non-prod", "Prod-View", 1)
set_perm("production", "Prod-View", 1)

print("\n--- final team list ---")
print(json.dumps(call("GET", "/api/teams/search"), indent=1))
