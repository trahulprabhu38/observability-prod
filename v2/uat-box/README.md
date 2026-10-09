# UAT-environment box  (10.200.2.48)

Single server hosting both `UAT-ind` and `UAT-uae` Coolify environments (18
apps + 1 Postgres DB `ledger-india-uat`). See
`../../Desktop/valura/PARTNER_APPS_AND_UAT_INVENTORY.md` §4 for the app list.

| Agent | Port | Status |
|---|---|---|
| node-exporter | :9100 | already in `prometheus/targets/node-fleet.yml` (`box: uat-env`) — compose committed here, deployed. |
| cAdvisor | :8085 | already in `prometheus/targets/cadvisor-fleet.yml` (`box: uat-env`) — compose committed here, deployed. |
| Alloy | :12345 / :4317 / :4318 | **missing** — no logs/trace forwarding from this box. `alloy/` here is net-new, same pattern as `../dev-box/`. |

The host-level metrics (CPU/mem/disk) have been scrapeable for a while; what
was missing was the **per-app dashboard** — see
`../grafana/provisioning/dashboards/json/partner-apps/uat.json`. Its log
panels will show "no data" until Alloy is actually deployed here.

## Deploy Alloy (once reviewed)

```bash
scp -r alloy root@10.200.2.48:/root/
# on 10.200.2.48 (root):
cd /root/alloy && docker compose up -d
```
