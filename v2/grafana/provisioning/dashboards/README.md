# Provisioned dashboards

Everything in `json/` is auto-loaded by Grafana on start and re-read every 30s
(`dashboards.yml`). Two sources:

| Kind | Files | Datasource |
|---|---|---|
| Hand-written for v2 | `stack-health.json` | Prometheus / Loki |
| Pulled from grafana.com | via `../../scripts/fetch-dashboards.sh` (`node-exporter-full`, `cadvisor`, `loki-logs`, `otel-collector`) | Prometheus / Loki |
| **Imported from the old prod Grafana** (`grafana-infra`) | the rest, listed below | see table |

## Imported from prod

Collected from the prod instance (Grafana 12.3.2) and re-pointed at v2's
provisioned datasource UIDs. The verbatim originals are kept in
`../../../prod-prometheus-setup/grafana/dashboards/`.

| File | Title / uid | Datasource in v2 | Notes |
|---|---|---|---|
| `dev-server-logs.json` | Dev Server logs · `dev-docker-logs-v2` | Loki | clean port (UID remap only) |
| `valura-loki-logs.json` | loki logs · `dev-docker-logs-v3` | Loki | clean port; near-duplicate of the above |
| `valura-error-logs.json` | Valura Error Logs · `valura-errlogs` | Loki | clean port |
| `infraserver-cadvisor.json` | InfraServer-cAdvisor · `nexus-cadvisor-v1` | Prometheus | clean port; `$datasource` var defaults to `prometheus` |
| `cloudflare-analytics.json` | valura.ai – Cloudflare Analytics · `valura-cf-v3` | Infinity | all panels use **inline sample data** (it's a mockup, not a live feed). Needs the `yesoreyeram-infinity-datasource` plugin (installed via `GF_INSTALL_PLUGINS`) but no Cloudflare token. |
| `aws-alb.json` | AWS ALB · `aws-alb-only` | Prometheus (**rewritten**) | CloudWatch → PromQL against YACE. See caveats. |
| `aws-ecs-metrics.json` | AWS ECS – metrics · `testtt` | Prometheus (**rewritten**) | CloudWatch → PromQL against YACE. "Service Logs" row removed. |
| `aws-rds.json` | AWS RDS · `aws-rds-v2` | Prometheus (**rewritten**) | CloudWatch → PromQL against YACE. |
| `aws-ecs-container-logs.json` | AWS ECS – container logs · `aws-ecs-final` | **CloudWatch** | kept as-is: CloudWatch Logs Insights has no Prometheus/Loki equivalent. Needs the opt-in CloudWatch datasource (commented in `datasources.yml`). |

## Caveats for the rewritten AWS dashboards

These three (`aws-alb`, `aws-ecs-metrics`, `aws-rds`) originally queried the
CloudWatch datasource directly. v2 pulls the same numbers through **YACE** into
Prometheus instead (`ecs/yace/config.yml`, compose profile `ecs`). Every panel
target was rewritten from a CloudWatch metric spec to a PromQL query of the form:

```
aws_<namespace>_<metric>_<stat>{dimension_<Dim>=~"$var"}
```

Because the transport changed, a few things differ from prod — check these first
if a panel is empty:

1. **Metric names are YACE-generated.** The rule used here: lowercase the
   CloudWatch metric name, insert `_` at every lower→UPPER boundary, append the
   statistic (`_average`, `_sum`, `_p95`, …). YACE's exact spelling can vary by
   version (e.g. `un_healthy_host_count` vs `unhealthy_host_count`). Confirm
   against `http://localhost:9090/api/v1/label/__name__/values` after
   `make ecs-up`.
2. **`$period` is gone.** CloudWatch's per-query period has no PromQL analogue;
   YACE's scrape interval + `period:`/`length:` in its config decide resolution.
3. **Region filter dropped from queries.** Fine for a single-region setup; add
   `region=~"$region"` back to the exprs if YACE scrapes multiple regions.
4. **Cluster-level panels also show per-service series.** The old queries used
   CloudWatch `matchExact`; the PromQL selectors only pin `dimension_ClusterName`,
   so Container-Insights series that also carry `dimension_ServiceName` come
   through too. Add `dimension_ServiceName=""` to isolate the cluster aggregate.
5. **"Capacity Provider Reservation" stays empty.** `AWS/ECS/ManagedScaling`
   isn't a YACE discovery type — see the note in `ecs/yace/config.yml`.
6. **Counter panels show CloudWatch's per-period Sum**, not a Prometheus rate.
   The shape matches prod; don't wrap these in `rate()`.

## Re-importing / refreshing from prod

```bash
../../../prod-prometheus-setup/scripts/fetch-grafana-dashboards.sh
```

That re-pulls the verbatim originals into `prod-prometheus-setup/`. Re-porting to
v2 (UID remap + the AWS rewrites) is a manual step — this folder is the target.
