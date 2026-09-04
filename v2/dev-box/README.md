# dev-box agents  (10.200.2.51 – Coolify "satyam")

What runs on the dev box so the v2 stack on `10.200.2.52` can see it. These
compose files live **on `.51`** at `/root/{alloy,cadvisor,node-exporter}/`; the
copies here are the source of truth – edit here, `scp` up, `docker compose up -d`.

| Agent | On .51 | Port | Scraped / received by (.52) |
|---|---|---|---|
| `node-exporter` | `/root/node-exporter` | `:9100` (host net) | Prometheus job `node-fleet` → `box="valura-dev"` |
| `cadvisor` | `/root/cadvisor` | `:8086` | Prometheus job `cadvisor-fleet` → `box="valura-dev"` |
| `alloy` | `/root/alloy` | `:12345` UI, `:4317/:4318` OTLP | logs → Loki `:3100`; traces → OTel Collector `:4317` |

## Region attribution (UAE vs IND)

Region == Coolify **project**:

| Region | `coolify.projectName` |
|---|---|
| **UAE** | `valura-development` |
| **IND** | `global-valura-dev` |

- **Metrics**: cAdvisor is **v0.52.1** with `--store_container_labels=false
  --whitelisted_container_labels=coolify.projectName,coolify.resourceName,coolify.environmentName`
  and an explicit `-v /var/run/docker.sock` + `--docker=unix:///var/run/docker.sock`.
  v0.49 (the previous image) **could not read the Docker API** on this
  Docker-29 / cgroup-v2 / PVE-LXC host, so every container came back as the
  root cgroup with no name/labels. The whitelisted labels surface as
  `container_label_coolify_projectName` / `_resourceName` / `_environmentName`.
- **Logs**: `alloy/config.alloy` promotes the same Coolify labels to Loki
  stream labels `coolify_project` / `coolify_resource` / `coolify_env`, plus
  `host="dev-server-1"`, `job="docker-containers"`.
- **Traces**: `alloy/config.alloy` runs an `otelcol.receiver.otlp` on
  `:4317/:4318` and forwards to `10.200.2.52:4317`. Apps are **not yet
  instrumented** – see `../../docs/dev-dashboards.md`.

## Firewall note

`.51` runs **ufw**. Host-network agents (node-exporter) are NOT covered by
Docker's iptables bypass, so an explicit rule is required:

```
ufw allow from 10.200.2.52 to any port 9100 proto tcp
```

cAdvisor is a *published* container port (`-p 8086:8080`) so Docker's own
rules already allow it.

## Redeploy

```bash
# on 10.200.2.51
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor     && docker compose up -d      # ~90s first-scrape warmup
cd /root/alloy        && docker compose up -d
```
