# ECS task-level metrics via `prometheus-ecs-discovery`

Use this when **your own application containers on ECS expose a `/metrics`
endpoint** (Prometheus client library) and you want Prometheus to scrape each
running task directly - not just CloudWatch aggregates.

## How it works

```
prometheus-ecs-discovery  --(every 60s)-->  ECS + EC2 APIs
        |  writes  ecs_file_sd.yml  (list of task IP:port + labels)
        v
Prometheus  file_sd  ->  scrapes each task's /metrics
```

`prometheus-ecs-discovery` is a small Go binary/container from the Prometheus
community (`tkgregory/prometheus-ecs-discovery` or build from
`github.com/teralytics/prometheus-ecs-discovery`). It needs read-only ECS/EC2
permissions and must be able to reach the task IPs (run it inside the VPC, or use
`awsvpc` networking + a peered/again VPN link to your observability box).

## Run it (compose snippet)

Add to `docker-compose.yml` (or run on a box inside the AWS VPC):

```yaml
  ecs-discovery:
    image: tkgregory/prometheus-ecs-discovery:latest
    container_name: ecs-discovery
    restart: unless-stopped
    profiles: ["ecs"]
    env_file: [.env]                 # AWS_* creds
    command:
      - "-config.write-to=/output/ecs_file_sd.yml"
      - "-config.scrape-interval=60s"
      - "-config.region=ap-south-1"
    volumes:
      - ./prometheus/targets:/output
    networks: [monitoring]
```

Then in `prometheus/prometheus.yml` uncomment:

```yaml
  - job_name: ecs-tasks
    file_sd_configs:
      - files: ["/etc/prometheus/targets/ecs_file_sd.yml"]
        refresh_interval: 60s
```

## Telling the discovery which tasks to scrape

It reads **Docker labels / ECS task-definition `dockerLabels`**:

```json
"dockerLabels": {
  "PROMETHEUS_EXPORTER_PORT": "9779",
  "PROMETHEUS_EXPORTER_PATH": "/metrics"
}
```

Only tasks carrying `PROMETHEUS_EXPORTER_PORT` get written to the file_sd output.

## IAM policy (read-only)

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": [
      "ecs:ListClusters", "ecs:ListTasks", "ecs:DescribeTasks",
      "ecs:DescribeContainerInstances", "ecs:DescribeTaskDefinition",
      "ec2:DescribeInstances"
    ],
    "Resource": "*"
  }]
}
```

## When to prefer this vs YACE vs ADOT

| Need | Use |
|---|---|
| ECS/Fargate CPU/mem, task counts, ALB - no app changes | **YACE** (`../yace/`) |
| Your app's own Prometheus metrics, per task | **this** (`prometheus-ecs-discovery`) |
| Push model, no inbound access to tasks, OTel-native | **ADOT sidecar** (`../adot/`) |
