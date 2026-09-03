# Running node-exporter inside a Proxmox LXC container

Full background and the "host vs container" discussion is in
`../docs/06-lxc-proxmox.md`. This file is just the copy-paste install.

## Option 1 - systemd service inside the LXC (recommended for per-container OS metrics)

Run **inside the container** (Debian/Ubuntu template):

```bash
# as root inside the LXC
VER=1.8.2
useradd --no-create-home --shell /usr/sbin/nologin node_exporter || true
curl -fsSL "https://github.com/prometheus/node_exporter/releases/download/v${VER}/node_exporter-${VER}.linux-amd64.tar.gz" \
  | tar -xz -C /tmp
install -m 0755 "/tmp/node_exporter-${VER}.linux-amd64/node_exporter" /usr/local/bin/node_exporter

cat >/etc/systemd/system/node_exporter.service <<'EOF'
[Unit]
Description=Prometheus Node Exporter
After=network-online.target
Wants=network-online.target

[Service]
User=node_exporter
Group=node_exporter
Type=simple
ExecStart=/usr/local/bin/node_exporter \
  --collector.systemd \
  --collector.processes \
  --web.listen-address=0.0.0.0:9100
Restart=on-failure
NoNewPrivileges=true
ProtectHome=yes
ProtectSystem=strict

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now node_exporter
curl -s localhost:9100/metrics | head
```

Then on the observability box add the container to
`prometheus/targets/node-fleet.yml`:

```yaml
- targets: ["10.0.0.20:9100"]
  labels: { box: lxc-postgres, kind: lxc, env: prod }
```

`make reload-prometheus` and check **Status -> Targets** in Prometheus.

### Caveats for LXC (important)

- Inside an **unprivileged LXC** some `/proc` and `/sys` paths are the *host's*,
  not the container's. CPU/mem/net numbers are usually per-container (cgroup
  aware on modern kernels), but **filesystem** and some **hwmon**/thermal
  collectors report host or nothing. Disable the noisy ones:
  `--no-collector.thermal_zone --no-collector.hwmon --no-collector.nfs`.
- `node_filesystem_*` inside the LXC reflects the container's mounts - fine.
- For accurate **disk I/O** and **pressure stall (PSI)** you often need the
  metrics from the Proxmox host instead (Option 2).

## Option 2 - one node-exporter on the Proxmox HOST

Covers the hypervisor and, via cgroup metrics, aggregate container usage.
Install with the same systemd unit above but on the PVE host. Add
`--collector.cgroups` if you want per-cgroup breakdowns.

Also add **`prometheus-pve-exporter`** for Proxmox-native data (VM/CT status,
per-CT CPU/mem/disk quota, storage pools, cluster health) - see
`../docs/06-lxc-proxmox.md`.

## Option 3 - a tiny compose file per Docker-capable LXC

If the LXC runs Docker, drop this in and `docker compose up -d`:

```yaml
services:
  node-exporter:
    image: prom/node-exporter:v1.8.2
    restart: unless-stopped
    network_mode: host
    pid: host
    command:
      - "--path.rootfs=/host"
      - "--no-collector.thermal_zone"
      - "--no-collector.hwmon"
    volumes:
      - "/:/host:ro,rslave"
```
