# 05 - Collecting ECS / Fargate metrics

ECS is different from your LXC/Docker boxes: **you don't get a shell on the
host** (especially Fargate). So "install node-exporter" isn't an option. There
are four real approaches. Pick by what you need.

| # | Approach | Gets you | App changes | Network | Effort |
|---|---|---|---|---|---|
| A | **CloudWatch via YACE** | ECS/Fargate CPU/mem, task counts, ALB, Container Insights | none | outbound to AWS API | low |
| B | **prometheus-ecs-discovery** | your app's own `/metrics` per task | expose `/metrics` | Prometheus must reach task IPs | medium |
| C | **ADOT sidecar** | per-task CPU/mem/net/disk from task metadata | add a sidecar | task pushes out (remote-write) | medium |
| D | **node-exporter + cAdvisor daemon** (EC2 launch type only) | full host + container metrics | none | Prometheus reaches the EC2 hosts | medium |

Most people run **A + B** together: A for infra health, B for app internals.
Fargate users who can't open inbound to tasks use **A + C**.

---

## A - CloudWatch via YACE (start here)

`yet-another-cloudwatch-exporter` calls the CloudWatch API and re-exposes the
results as Prometheus metrics. Everything AWS already measures about ECS is in
CloudWatch; YACE just makes it scrapeable.

### Enable it

```bash
cp .env.example .env         # fill AWS_ACCESS_KEY_ID / SECRET / REGION
make ecs-up                  # = docker compose --profile ecs up -d
```

Then uncomment the `ecs-cloudwatch` job in `prometheus/prometheus.yml` and
`make reload-prometheus`.

### Config

`ecs/yace/config.yml` - already has jobs for:
- `AWS/ECS` namespace: service/cluster `CPUUtilization`, `MemoryUtilization`
- `ECS/ContainerInsights`: `RunningTaskCount`, `PendingTaskCount`,
  `CpuUtilized/Reserved`, `MemoryUtilized/Reserved`, network, ephemeral storage
  (**requires Container Insights enabled** on the cluster:
  `aws ecs update-cluster-settings --cluster X --settings name=containerInsights,value=enabled`)
- `AWS/ApplicationELB`: request count, 5xx, `TargetResponseTime` p95, healthy hosts

Metric names come out as `aws_ecs_cpuutilization_average`,
`aws_ecs_containerinsights_running_task_count_average`,
`aws_applicationelb_httpcode_target_5xx_count_sum`, etc. Tags you list under
`exportedTagsOnMetrics` become labels (e.g. `tag_Environment`).

### IAM policy (read-only)

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "tag:GetResources",
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListMetrics",
      "apigateway:GET",
      "ecs:ListClusters", "ecs:ListServices", "ecs:DescribeServices"
    ],
    "Resource": "*"
  }]
}
```

Prefer an **IAM role** (IRSA / instance profile) over static keys where you can.

### Cost & latency caveats

- `GetMetricData` is billed per metric per request. `period: 300` (5 min) keeps
  cost sane; don't set `period: 60` on hundreds of series without checking the
  bill.
- CloudWatch data is **delayed** (1-5 min for standard, sometimes more for
  Container Insights). Not for sub-minute debugging - that's what B/C are for.
- YACE `length` must be >= `period`. `delay` can offset for late-arriving data.

---

## B - Task-level app metrics via `prometheus-ecs-discovery`

Your containers already expose Prometheus metrics (client library on
`/metrics:9779` or wherever). A discovery process lists running ECS tasks and
writes a `file_sd` file; Prometheus scrapes each task directly.

Full setup: `ecs/ecs-discovery/README.md`. Summary:

1. Run `prometheus-ecs-discovery` (container or binary) with read-only
   ECS/EC2 permissions, writing to `prometheus/targets/ecs_file_sd.yml`.
2. Mark scrapable tasks in their task definition:
   `"dockerLabels": { "PROMETHEUS_EXPORTER_PORT": "9779" }`.
3. Uncomment the `ecs-tasks` job in `prometheus/prometheus.yml`.
4. **Networking**: Prometheus must reach the task IPs. Fine if the observability
   box is in/peered-to the VPC. On Fargate with `awsvpc`, tasks get ENI IPs -
   still need a route + security-group rule from the obs box to the task port.

---

## C - ADOT sidecar (push model, no inbound access needed)

Run the AWS Distro for OpenTelemetry Collector as a sidecar in each task. It
reads the **ECS task metadata endpoint** (per-task CPU/mem/net/disk, no app
changes) and **remote-writes** to your Prometheus.

Full setup incl. task-definition JSON and the sidecar config:
`ecs/adot/README.md`.

Use this when you **can't or won't open inbound** to Fargate tasks, or you want
the OTel model end to end. Cost: a small sidecar (128 CPU / 256 MB) per task.

The same ADOT sidecar can also receive your app's **OTLP traces** and forward
them to the observability box's otel-collector - one sidecar, all signals.

---

## D - EC2 launch type: node-exporter + cAdvisor as a daemon service

If your ECS runs on **EC2** (not Fargate), the container instances are real
Linux hosts you control. Run a **daemon** ECS service (one task per instance)
with two containers:

- `prom/node-exporter` with the host `/proc`, `/sys`, `/` mounted (host CPU/mem/disk)
- `gcr.io/cadvisor/cadvisor` (per-container metrics, same as your Docker boxes)

Publish them on host ports (`9100`, `8080`), then add the instances to
`prometheus/targets/node-fleet.yml` / `cadvisor-fleet.yml` - **exactly the same
fleet pattern as your other boxes**. Discover instance IPs with
`prometheus-ecs-discovery` or an EC2 SD config.

Not possible on Fargate (no host).

---

## Which metrics matter for ECS

| Question | Metric (source) |
|---|---|
| Is the service at desired capacity? | `RunningTaskCount` vs `DesiredTaskCount` (A) |
| Are tasks getting killed / failing to start? | `PendingTaskCount` climbing, task stopped events, `CpuReserved` vs limit |
| Is a task CPU-throttled? | `CpuUtilized / CpuReserved` -> ~100% (A/C) |
| Is a task about to OOM? | `MemoryUtilized / MemoryReserved` -> >90% (A/C) |
| Is the ALB seeing errors? | `HTTPCode_Target_5XX_Count`, `TargetResponseTime` p95 (A) |
| App-level (queue depth, business KPIs) | your own `/metrics` (B) or OTLP |

---

## Recommended starting point for you

1. **A (YACE)** now - `make ecs-up`, uncomment the job, get ECS service CPU/mem
   and `RunningTaskCount` into Grafana. Zero app changes.
2. Add **B** when you want your apps' own metrics per task and the obs box can
   reach the VPC.
3. Switch B -> **C** if inbound-to-tasks is a non-starter (strict Fargate).

---

## Imported AWS dashboards

The old prod Grafana had four CloudWatch-datasource dashboards (ALB, ECS
metrics, ECS container logs, RDS). In v2 they land like this:

| Dashboard (`json/…`) | How it works in v2 |
|---|---|
| `aws-alb.json`, `aws-ecs-metrics.json`, `aws-rds.json` | **Rewritten to PromQL** against YACE metrics. No CloudWatch datasource needed - `make ecs-up` and the panels fill in. |
| `aws-ecs-container-logs.json` | Still **CloudWatch Logs Insights** - there's no Prometheus/Loki equivalent for that query language. Enable the commented `CloudWatch` datasource in `grafana/provisioning/datasources/datasources.yml`. |

To feed the three rewritten dashboards, `ecs/yace/config.yml` was expanded from
the starter metric list to the full set they query - all of `AWS/RDS`, the ALB
status-code / latency-percentile / connection metrics, and the extra
`ECS/ContainerInsights` series (`ServiceCount`, `DeploymentCount`, storage,
ephemeral storage). `GetMetricData` is billed per metric per request, so trim
anything you don't look at.

Gotchas are listed in
[`grafana/provisioning/dashboards/README.md`](../grafana/provisioning/dashboards/README.md)
- the short version: YACE metric spelling can vary by version (check
`http://localhost:9090/api/v1/label/__name__/values`), cluster-level panels also
show per-service series, and the "Capacity Provider Reservation" panel stays
empty because `AWS/ECS/ManagedScaling` isn't a YACE discovery type.
