# partner-apps box  (10.200.1.2, hostname `caddy`)

Same pattern as `../dev-box/` and `../stg-box/`. This is a big shared edge box
(200 cores, 150GB RAM, 88 containers, Proxmox LXC like `.51`) hosting several
Coolify projects; the one this dashboard cares about is **`partner-apps`**
(31 containers today) - white-label replicas of the web app carrying each
partner's integration/branding.

| Agent | Port | Notes |
|---|---|---|
| node-exporter | :9100 | new; ufw rule added (`allow from 10.200.2.52`) |
| cAdvisor v0.52.1 | :8085 | new. This box is a Proxmox LXC like `.51`, so the explicit-docker.sock fix works cleanly (unlike the KVM-VM `.57` - see `../stg-box/README.md`) |
| Alloy | :12345 / :4317 / :4318 | already existed (bare `docker run`, `env=production, host=edge`, no region labels, no OTLP). Redeployed via compose with `coolify_project/resource/env` labels, the level-normalisation pipeline, and an OTLP receiver forwarding to `.52:4317` |

Other Coolify projects sharing this box (not covered by the `partner-apps`
dashboard): `n-1`, `valura`, `global-valura-dev`, `global-valura-staging`,
`runway`, `valura-predev`, `valura-os`, `pump-bot`, `valura-development`.
Their containers still show up in cAdvisor/Alloy output (harmless) but the
dashboard's `coolify_project="partner-apps"` filter excludes them.

## Redeploy

```bash
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor      && docker compose up -d
cd /root/alloy         && docker compose up -d
```
