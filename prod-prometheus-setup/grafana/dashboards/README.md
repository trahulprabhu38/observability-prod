# Prod Grafana dashboards (collected)

Verbatim export of every dashboard on the prod Grafana instance
(`grafana-infra.valura.co.in`, Grafana 12.3.2), one bare dashboard JSON per file.
`id` is nulled and `version` stripped so each file imports cleanly anywhere;
`uid`, panels, queries and template variables are untouched.

Regenerate with:

```bash
GRAFANA_USER=valuraadmin GRAFANA_PASS='...' \
  ../../scripts/fetch-grafana-dashboards.sh
```

(or `GRAFANA_TOKEN=...`). Files are named `<folder>/<title-slug>.json`.

| File | Title | uid | Datasource |
|---|---|---|---|
| `aws/aws-alb-application-load-balancer.json` | AWS ALB — Application Load Balancer | `aws-alb-only` | CloudWatch |
| `aws/aws-ecs-individual-metrics.json` | AWS ECS - individual metrics | `testtt` | CloudWatch |
| `aws/aws-ecs-individual-container-logs.json` | AWS ECS — individual container logs | `aws-ecs-final` | CloudWatch Logs Insights |
| `aws/aws-rds-relational-database.json` | AWS RDS — Relational Database | `aws-rds-v2` | CloudWatch |
| `general/dev-server-logs.json` | Dev Server logs | `dev-docker-logs-v2` | Loki |
| `general/loki-logs.json` | loki logs | `dev-docker-logs-v3` | Loki |
| `general/valura-error-logs.json` | Valura Error Logs | `valura-errlogs` | Loki |
| `general/infraserver-cadvisor.json` | InfraServer-cAdvisor | `nexus-cadvisor-v1` | Prometheus |
| `general/valura-ai-cloudflare-analytics.json` | valura.ai — Cloudflare Analytics | `valura-cf-v3` | Infinity (inline sample data) |

## Datasources referenced (as configured in prod, by UID)

| UID | Name | Type |
|---|---|---|
| `PBFA97CFB590B2093` | Prometheus | prometheus (default) |
| `P8E80F9AEF21F6940` | Loki | loki |
| `cflwvn5uqm77kf` | cloudwatch | cloudwatch (`ap-south-1`) |
| `aflqsyjh3qneoc` | yesoreyeram-infinity-datasource | Infinity → `api.cloudflare.com` |

These datasources were created in the prod Grafana UI, not provisioned from
files, so there is no datasource YAML in this repo to match.

## Where these go next

The v2 stack imports re-pointed copies of all nine — see
[`../../../v2/grafana/provisioning/dashboards/README.md`](../../../v2/grafana/provisioning/dashboards/README.md).
The Loki/Prometheus ones port 1:1; the CloudWatch metric dashboards were
rewritten to PromQL against YACE.
