# ECS metrics via an ADOT sidecar (push model)

**ADOT** = AWS Distro for OpenTelemetry Collector. Run it as a **sidecar
container** in each ECS task. It scrapes the ECS task-metadata endpoint (per-task
CPU/mem/network/disk with no app changes) and **remote-writes** the result to
your Prometheus - so no inbound firewall hole to the tasks is needed.

```
ECS task
 ┌───────────────┐   scrape task metadata :51678 / ECS_CONTAINER_METADATA_URI_V4
 │ app container │◄───────────────┐
 ├───────────────┤                │
 │ adot sidecar  │  prometheusremotewrite  ─────►  http://<obs-box>:9090/api/v1/write
 └───────────────┘
```

## 1. Sidecar collector config (`adot-config.yaml`)

Store it in SSM Parameter Store (e.g. `/ecs/adot/config`) and reference it from
the task definition, or bake it into a custom image.

```yaml
receivers:
  awsecscontainermetrics:            # <-- the ECS task-level receiver
    collection_interval: 20s

processors:
  batch/metrics:
    timeout: 30s
  resourcedetection:
    detectors: [env, ecs]
  filter/only-useful:
    metrics:
      include:
        match_type: strict
        metric_names:
          - ecs.task.memory.utilized
          - ecs.task.memory.reserved
          - ecs.task.cpu.utilized
          - ecs.task.cpu.reserved
          - ecs.task.network.rate.rx
          - ecs.task.network.rate.tx
          - ecs.task.storage.write_bytes
          - ecs.task.storage.read_bytes

exporters:
  prometheusremotewrite:
    endpoint: "http://OBS_BOX_IP:9090/api/v1/write"
    resource_to_telemetry_conversion:
      enabled: true                  # keep ecs.* resource attrs as labels

service:
  pipelines:
    metrics:
      receivers: [awsecscontainermetrics]
      processors: [resourcedetection, filter/only-useful, batch/metrics]
      exporters: [prometheusremotewrite]
```

## 2. Task definition sidecar entry

```json
{
  "name": "adot-collector",
  "image": "public.ecr.aws/aws-observability/aws-otel-collector:latest",
  "essential": false,
  "cpu": 128,
  "memory": 256,
  "secrets": [
    { "name": "AOT_CONFIG_CONTENT", "valueFrom": "arn:aws:ssm:ap-south-1:ACCOUNT:parameter/ecs/adot/config" }
  ],
  "logConfiguration": {
    "logDriver": "awslogs",
    "options": {
      "awslogs-group": "/ecs/adot-collector",
      "awslogs-region": "ap-south-1",
      "awslogs-stream-prefix": "adot"
    }
  }
}
```

The task role needs `ssm:GetParameters` for that parameter. No extra ECS/EC2
permissions - the metadata endpoint is local to the task.

## 3. Prometheus side

Nothing to add. `--web.enable-remote-write-receiver` is already set on the
`prometheus` service, so `POST /api/v1/write` just works. Filter in Grafana on
`aws_ecs_...` / `ecs_task_...` metric names and the `aws.ecs.*` labels.

> Make sure the observability box's :9090 is reachable from the ECS subnets
> (VPN / peering / private link) and consider putting an auth proxy in front of
> the remote-write path if it crosses untrusted networks.

## Trade-offs

+ No inbound access to tasks; scales with the tasks themselves.
+ Pure OTel - same mental model as the traces pipeline.
- A sidecar in every task (small CPU/mem cost, more moving parts).
- App's own business metrics still need the OTLP exporter or `prometheus-ecs-discovery`.
