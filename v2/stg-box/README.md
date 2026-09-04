# staging box agents  (10.200.2.56 UAE, 10.200.2.57 IND)

Same pattern as `../dev-box/` (10.200.2.51), applied to the two staging
Coolify hosts. Configs here are mirrors — edit here, `scp` up, `docker compose
up -d` on the actual box.

| Box | Region | Coolify project | Agents |
|---|---|---|---|
| `10.200.2.56` (hostname `UAE-staging`) | UAE | `valura-uae-staging` | node-exporter :9100, cAdvisor :8085, Alloy :12345/4317/4318 |
| `10.200.2.57` (hostname `valura-ind-stg`) | IND | `global-valura-staging` | node-exporter :9100, cAdvisor :8085 **(no per-container data, see below)**, Alloy :12345/4317/4318 |

Both boxes already had cAdvisor + a bare-bones `valura-alloy-logs` (logs-only,
no region labels, no trace receiver) before this — that's why `cadvisor-fleet`
already had `.56`/`.57` entries in `prometheus/targets/`. What was added:

- **node-exporter** (new)
- **cAdvisor**: `.56` redeployed to v0.52.1 for consistency (it already worked
  at v0.49 - Docker 28.1.1 there talks to cAdvisor fine). `.57` also bumped to
  v0.52.1 - **see the known issue below**, it doesn't help there.
- **Alloy**: added `coolify_project` / `coolify_resource` / `coolify_env`
  labels, the same `level` normalization pipeline as `../dev-box/`, and an
  OTLP receiver (:4317/:4318) forwarding traces to `10.200.2.52:4317`.
  Redeployed via a proper compose file (previously a bare `docker run`, no
  compose project, no ports published).

## Known issue: no per-container metrics on `.57`

cAdvisor v0.52.1 on `10.200.2.57` registers its Docker (and containerd)
factory cleanly but returns **zero containers** - `container_last_seen` only
shows `id="/"` plus every systemd unit under `system.slice`, never a single
`docker-<id>.scope`, even though those cgroup directories exist on disk
(`ls /sys/fs/cgroup/system.slice/` shows dozens) and a plain `docker ps` /
`docker inspect` from another container works fine (Alloy proves this - it
enumerates containers via the same docker.sock without issue).

Tried and ruled out (all on v0.52.1, all "registered successfully" per logs,
none changed the result):
- explicit `-v /var/run/docker.sock:/var/run/docker.sock` + `--docker=unix://...`
  (this alone fixed the identical symptom on `.51`)
- `--cgroupns=host` (Docker 29 defaults to a private cgroup namespace per
  container, which normally hides sibling cgroups entirely - this looked like
  the smoking gun since cAdvisor's own PID then correctly showed up at
  `/system.slice/docker-<id>.scope`, but sibling `docker-*.scope` dirs still
  never appeared)
- explicit `-v /sys/fs/cgroup:/sys/fs/cgroup:ro` in addition to `/sys`
- mounting `/run/containerd/containerd.sock` for cAdvisor's containerd factory
- pinning `DOCKER_API_VERSION=1.44` (server supports 1.40-1.55)
- cAdvisor v0.49.1 (matching `.56`'s working version) + `--cgroupns=host`

`.51` and `.57` are both Docker 29.x + cgroup v2 + systemd driver, so it isn't
simply a version-family issue. `.51` is inside a Proxmox LXC (the LXC's own
cgroup boundary may already flatten this); `.57` is a real KVM VM. That's the
only structural difference found. Likely a cAdvisor bug specific to that
combination - worth re-testing against a newer cAdvisor release, or filing
upstream.

**Impact**: the `stg-IND` dashboard's CPU/memory/restarts panels show "No
data" (not errors - the query is fine, there's just nothing to return). Host
metrics (node-exporter), logs, and traces are all unaffected and fully
functional.

## Firewall

`.56` runs ufw (only 22 + 4000 allowed before this) - added
`ufw allow from 10.200.2.52 to any port 9100 proto tcp` for node-exporter.
`.57` has no firewall (ufw inactive).

## Redeploy

```bash
# on the target box (.56 or .57)
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor      && docker compose up -d
cd /root/alloy         && docker compose up -d
```
