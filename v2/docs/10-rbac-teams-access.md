# 10 - RBAC: teams, roles, prod vs general access

Two independent dimensions, both enforced through Grafana teams:

1. **Org role** (what you can *do*): Team Lead -> `Editor`, Developer -> `Viewer`.
2. **Access classification** (what you can *see*): `Prod-View` vs `General-View`,
   enforced via **folder permissions** - not org role.

## Login: GitHub SSO

Sign-in is **GitHub OAuth**, restricted to the `2CentsCapital` GitHub org.
Local email/password accounts still work (the `admin` user, plus anyone an
admin created by hand) but the normal path is "Sign in with GitHub".

Config lives in `grafana/grafana.ini` under `[auth.github]`; the OAuth client
id/secret come from `.env` (`GITHUB_OAUTH_CLIENT_ID` / `_SECRET`) so they stay
out of git. The GitHub OAuth app's **Authorization callback URL** must be
`https://grafana-infra.valura.co.in/login/github` - that host is also set as
`server.root_url`, which is what Grafana uses to build the redirect.

What SSO does:

- Authenticates the person and confirms they're in the `2CentsCapital` org
  (`read:org` scope).
- Auto-creates a Grafana user as **Viewer** on first login
  (`allow_sign_up = true`, `auto_assign_org_role = Viewer`).
- Because the `Viewer` role is granted View on `dev`, `staging` and
  `non-prod` (see *Folder permissions* below), the new person **can see
  those three folders immediately** - no team assignment, no admin step.

What SSO does *not* do:

- Grant `prod` or the global `deployments` folder. Those stay
  `Prod-View`-team-only. An admin adds someone to `Prod-View` (and usually a
  project team) via the onboarding step below when they need prod.
- Map GitHub org/team -> Grafana role or team (`role_attribute_path`,
  `team_ids`). Not wired up - Enterprise-only for OAuth anyway, and
  `Prod-View` membership stays a manual, reviewed decision.

This is a deliberate softening of the old "zero teams = zero dashboards"
rule: now that login is hard-restricted to one GitHub org, "any authenticated
Viewer" and "the General-View audience" are the same set of people, so
dev/staging/non-prod visibility is just the Viewer-role default. `prod` is
the only tier that still gates on team membership.

To revoke someone: remove them from the `2CentsCapital` GitHub org (blocks
new logins) and disable/delete the Grafana user (kills existing sessions).

## Folders

Organized by SDLC stage (dev/staging/prod), not by product - this is what
makes "developers get their own deployment dashboards without needing prod
access" possible.

| Folder | Contains | Who sees it |
|---|---|---|
| `dev` | dev-UAE, dev-IND, infra-dev, deployments-dev, deployment-builds-dev | any logged-in user (Viewer role) |
| `staging` | stg-UAE, stg-IND, infra-stg-uae, infra-stg-ind, deployments-staging, deployment-builds-staging | any logged-in user (Viewer role) |
| `prod` | prod-UAE, infra-prod-uae, deployments-prod, deployment-builds-prod, aws-ecs-metrics, aws-alb, aws-ecs-container-logs (ECS/CloudWatch, valura-global-prod-cluster) | Prod-View only |
| `non-prod` | partner-apps, infra-partner-apps, infra-observability, stack-health, aws-rds (unfed), and the imported Cloudflare/general dashboards | any logged-in user (Viewer role) |
| `deployments` | the GLOBAL deployments/deployment-builds pair - all 181 apps across every client project on the Coolify instance, not just ours | Prod-View only |

`partner-apps` and `infra-observability` deliberately stay in `non-prod`
rather than moving into `prod` - Coolify's own environment label calls
partner-apps "production", but it's never been treated as prod-sensitive
here (moving it into the Prod-View-only `prod` folder would have quietly cut
developers off from something they could already see). `infra-observability`
is the stack's own host, not part of the UAE/IND dev->staging->prod
pipeline this split models.

Declared via the filesystem, not the UI - `grafana/provisioning/dashboards/json/<folder>/*.json`
with `foldersFromFilesStructure: true` in `dashboards.yml`. To move a dashboard
between folders, move its JSON file; Grafana re-syncs within 30s.
`scripts/gen-dashboards.py` and `scripts/gen-infra-dashboards.py` each take a
`folder` field per entry and write straight into the right subfolder, so
regenerating them keeps this layout automatically. `gen-deploy-dashboard.py`
and `gen-build-status-dashboard.py` each build one global dashboard
(`deployments` folder) plus three scoped ones (`dev`/`staging`/`prod`
folders, filtered by Coolify project name - see their `SCOPES` dict).

(Named `non-prod`, not `general` - Grafana reserves the folder name "General"
for the default/root folder and refuses to create another one with that name.)

## Teams

| Team | Kind | Members |
|---|---|---|
| `UAE` | project | leads + devs on the UAE product |
| `IND` | project | leads + devs on the IND product |
| `Partner-Apps` | project | leads + devs on partner-apps |
| `Prod-View` | access | anyone who should see `prod` and the global `deployments` folder (they see `dev`/`staging`/`non-prod` too, like everyone) |
| `General-View` | access | legacy - `dev`/`staging`/`non-prod` is now the Viewer-role default for every logged-in user, so this team grants nothing extra. Kept as a grouping label; safe to stop using. |

Project teams carry **no folder permissions of their own** - they're purely
organisational (who's on which squad). The only access decision that still
matters is **`Prod-View` or not**: it's the sole gate on `prod` and the
global `deployments` folder. Everything else every authenticated user sees by
default.

## Folder permissions (View only - nobody edits provisioned dashboards)

```
non-prod     <- Viewer role (View), General-View (View), Prod-View (View)
dev          <- Viewer role (View), General-View (View), Prod-View (View)
staging      <- Viewer role (View), General-View (View), Prod-View (View)
prod         <- Prod-View (View)
deployments  <- Prod-View (View)
```

The `Viewer` **role** grant on `dev`/`staging`/`non-prod` is what makes a
fresh GitHub SSO login (auto-assigned org role Viewer) see those folders on
first login with no team step. The `General-View`/`Prod-View` team grants on
those same three folders are now redundant but left in place - harmless, and
they keep the script's output diff-free if you re-run it.

`prod` and `deployments` carry **only** the `Prod-View` team grant - no
Viewer/Editor role access - so a user who isn't in `Prod-View` still can't
see them, exactly as before. `grafana-setup-teams.py` sets all of this
(`set_perm` for the team grants, `set_role_perm` for the Viewer-role grants)
and is idempotent.

## Onboarding someone

**With GitHub SSO, most people need no onboarding at all**: they click "Sign
in with GitHub", get an auto-created Viewer account, and immediately see
`dev`/`staging`/`non-prod`. The only manual steps, and only when they apply:

- **Needs prod access** -> add them to `Prod-View`:
  `POST /api/teams/<Prod-View id>/members {"userId": <id>}`, or
  **Administration -> Teams** in the UI.
- **Is a team lead** (should be able to edit, not just view) -> bump org role:
  `PATCH /api/org/users/<id> {"role":"Editor"}`.
- **Project team** (`UAE`/`IND`/`Partner-Apps`) -> optional, organisational
  only; add via the UI if you want the squad grouping.

The script below is for **local (non-GitHub) accounts** - a break-glass
admin, a contractor outside the org, CI. It still creates the account, sets
the org role, and adds project + access teams:

```bash
./scripts/grafana-add-user.sh <email> "<full name>" '<temp password>' <team> <lead|dev> <prod|general>

# e.g. a UAE team lead who needs prod access:
./scripts/grafana-add-user.sh priya@company.com "Priya Sharma" 'TempPass123!' UAE lead prod

# e.g. an IND developer, general access only:
./scripts/grafana-add-user.sh raj@company.com "Raj Patel" 'TempPass123!' IND dev general
```

Creates the local account, sets the org role (Editor/Viewer), and adds them to
their project team + access team. `GRAFANA_AUTH` is required (the script
refuses to run without it - no credential is hardcoded in a file that's
committed to git):
`GRAFANA_AUTH=<admin-login>:<admin-password> GRAFANA_URL=https://grafana-infra.valura.co.in ./scripts/grafana-add-user.sh ...`
(omit `GRAFANA_URL` to default to `http://localhost:3000`, for running it
directly on `.52`). Tested end-to-end (created, verified role + both team
memberships, deleted) before this was committed. `grafana-setup-teams.py`
takes the same two env vars.

To change someone's access later: add/remove them from `Prod-View` /
`General-View` via **Administration -> Teams** in the UI, or the same
`/api/teams/:id/members` endpoint the script uses. To promote a dev to lead:
`PATCH /api/org/users/:id` with `{"role":"Editor"}`.

## Known quirk

Whoever creates a team via the API/UI is auto-added as an Admin-of-that-team
member (a Grafana behaviour, not something we set). `admin` shows up as a
member of all five teams for this reason - harmless, since `admin`'s access
comes from being a Grafana **Admin**, not from team membership.

## Verified: General-View can't see prod

Tested end-to-end with a throwaway `test` account (Viewer, `General-View`
only, no project team, deleted after): `/api/folders` correctly shows only
`non-prod`, and fetching the `production` folder directly is `403`.

This surfaced a real bug first: `prod-UAE` still showed up in `test`'s
`/api/search` results and was fetchable directly by UID (`200`, full JSON)
despite the folder being blocked. Cause: the dashboard carried its own
**direct, non-inherited** permissions (`{"role":"Viewer","permission":1}`,
`{"role":"Editor","permission":2}`) - a blanket grant to every org
Viewer/Editor that bypasses folder ACLs entirely. Dashboard-level permissions
in Grafana can override folder inheritance; only `prod-UAE` had this (audited
all 16 dashboards to confirm it wasn't systemic). Fixed by clearing it via
`POST /api/dashboards/id/:id/permissions` with `{"items": []}`.

`grafana-setup-teams.py` now sweeps every dashboard for this on each run and
strips any direct role-based grant it finds, so it can't silently recur - rerun
it after adding new dashboards if you want the same guarantee re-checked.
Re-verified after the fix: `test` saw exactly the 15 `non-prod` dashboards,
`prod-UAE` absent from search, direct fetch `403`.

## Verified: developers get dev/staging deployment dashboards, not prod

Re-tested after the dev/staging/prod folder split with the persistent `test`
account (Viewer, `General-View`, no project team): sees `dev` (5 dashboards),
`staging` (6), `non-prod` (13) - 24 total. `prod`, and the global
`deployments` folder, are both absent from search and `403` on direct UID
fetch (`prod-uae`, `deployments-prod`, `deployments`). `deployments-dev`
fetches `200`. The dashboard-permissions sweep in `grafana-setup-teams.py`
(see above) found nothing to clear on any of the new dashboards.

## Admin account

Renamed from the `admin`/`admin123` default to a named account (login/password
rotated via `PUT /api/users/:id` + `PUT /api/admin/users/:id/password`;
credentials live only in `v2/.env` - gitignored, never in this repo). To
rotate again later: same two calls, or
`docker exec grafana grafana-cli admin reset-admin-password '<new password>'`
for the password alone - then update `GRAFANA_ADMIN_PASSWORD` in `.env` to
match (that env var only seeds a *fresh* install; it does not reset an
existing account on restart).

## SSO

Done - GitHub OAuth, gated to the `2CentsCapital` org. See *Login: GitHub
SSO* near the top. The team/folder structure is unchanged; the only RBAC
change SSO brought is that `dev`/`staging`/`non-prod` are now the Viewer-role
default (so new users land with useful access) instead of requiring a
`General-View` team assignment.
