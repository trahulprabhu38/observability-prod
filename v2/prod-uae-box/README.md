# UAE production box  (10.200.2.54, hostname `prod-migration`)

**Production.** Coolify project `valura-prod` (14 containers: web, api, admin,
ogold/ogoldv2, ledger-backend/frontend, gtn/gtn-ws, analysis, ai-agents,
uae-bank-fees, zag). Handled with extra care - only new, additive,
self-contained containers were added; nothing app-facing was touched or
restarted.

| Agent | Port | Notes |
|---|---|---|
| node-exporter | :9100 | new; ufw rule added (`allow from 10.200.2.52`) |
| cAdvisor v0.52.1 | :8085 | new. **No per-container metrics** - same cAdvisor/cgroup limitation as `stg-IND` (see `../stg-box/README.md`): registers its Docker factory cleanly but returns zero containers. Host-level cAdvisor/node-exporter metrics are unaffected. |
| Alloy (`valura-alloy-logs`) | :12345 / :4317 / :4318 | already existed and was already working (`env=production, host=uae-prod`, shipping to `.52:3100`) - redeployed via compose with the `coolify_project/resource/env` labels, level-normalisation pipeline, and an OTLP receiver forwarding to `.52:4317`. Original config backed up at `/root/alloy/config.alloy.orig.bak` on the box; rollback command is in the deploy history if ever needed. |

## Pre-existing anomaly - left alone

This box also runs a **second**, already-broken Alloy container, `alloy-logs`
(status: restarting, crash-looping on its own before we ever touched this
box). It is **not** the one shipping logs - `valura-alloy-logs` is - and it
was left exactly as found. Not in scope; flag it to whoever owns this box if
it should be cleaned up.

## Redeploy

```bash
cd /root/node-exporter && docker compose up -d
cd /root/cadvisor      && docker compose up -d
cd /root/alloy         && docker compose up -d
```
