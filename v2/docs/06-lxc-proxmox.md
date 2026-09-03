# 06 - LXC containers & Proxmox metrics

You run workloads in **LXC containers on Proxmox**. There are three layers you
might want visibility into, and a different tool for each:

| Layer | Question | Tool |
|---|---|---|
| Inside a container | this CT's CPU/mem/disk/processes | **node-exporter inside the CT** |
| The hypervisor host | PVE node CPU/mem/disk/ZFS, kernel, NIC | **node-exporter on the PVE host** |
| Proxmox itself | CT/VM status, per-CT quotas, storage pools, cluster/quorum, backups | **prometheus-pve-exporter** |

You don't need all three on day one. Most useful combo: **node-exporter in each
important CT** + **pve-exporter once per cluster**.

---

## 1. node-exporter inside an LXC container

Gives you per-container OS metrics with the standard `node_*` names, so
**dashboard 1860 just works** and it slots into the same `node-fleet` job as
everything else.

Install: `../lxc/node-exporter-lxc.md` (systemd unit, or a one-container compose
file). Then add the CT to `prometheus/targets/node-fleet.yml`:

```yaml
- targets: ["10.0.0.20:9100"]
  labels: { box: lxc-postgres, kind: lxc, env: prod }
```

`make reload-prometheus` (actually not even needed - it's `file_sd`, re-read every
30s). Check **Status -> Targets** in Prometheus.

### LXC gotchas (read this)

An LXC container shares the host kernel. Some `/proc` and `/sys` files are the
**host's**, not the container's:

| Metric | Inside an LXC container | Fix / note |
|---|---|---|
| CPU (`node_cpu_seconds_total`) | usually **per-container** (cgroup-aware on modern kernels + lxcfs) | fine; Proxmox mounts lxcfs by default |
| Memory (`node_memory_*`) | per-container **if lxcfs is active** | Proxmox default = OK. Without lxcfs you'd see host totals |
| Load average | per-container with lxcfs | OK on Proxmox |
| Filesystem (`node_filesystem_*`) | the container's own mounts | OK |
| Disk I/O (`node_disk_*`) | **host-wide**, not per-container | get real per-CT I/O from pve-exporter or host cgroup metrics |
| Pressure stall (PSI) | often host-wide or missing | prefer host / pve-exporter |
| Thermal / hwmon / IPMI | host sensors or errors | **disable**: `--no-collector.thermal_zone --no-collector.hwmon --no-collector.nfs` |
| `node_boot_time_seconds` | may reflect the **host** boot | cosmetic; be aware for uptime panels |

Unprivileged containers (the Proxmox default, and the right choice) are more
restricted - the systemd hardening in the unit file
(`ProtectSystem=strict`, `NoNewPrivileges`) is fine; `--collector.systemd`
works if the CT runs systemd.

---

## 2. node-exporter on the Proxmox host

Covers the hypervisor: real disk I/O, ZFS ARC, NIC errors, ECC, host memory
pressure, and (via cgroups) aggregate per-CT usage.

Install the **same systemd unit** from `../lxc/node-exporter-lxc.md` on the PVE
node itself. Consider enabling `--collector.zfs` (ZFS pools) and
`--collector.cgroups` if you want raw per-cgroup breakdowns.

Add to `node-fleet.yml` with `kind: host`:

```yaml
- targets: ["10.0.0.10:9100"]
  labels: { box: pve-node-01, kind: host, env: infra }
```

> Don't expose `:9100` on the PVE host to the internet. Bind it to the mgmt
> network / firewall it to the observability box only.

---

## 3. prometheus-pve-exporter (Proxmox-native)

Talks to the Proxmox VE API and exposes `pve_*` metrics: guest up/down, per-CT
CPU/mem/disk **quota vs used**, storage pool usage, node/cluster health,
HA state, and (newer versions) backup job status.

### Create a read-only PVE API token

In the Proxmox UI: **Datacenter -> Permissions -> API Tokens -> Add**
- User: `root@pam` (or a dedicated `monitoring@pve` user)
- Token ID: `prometheus`
- **Uncheck** "Privilege Separation" for simplicity, or grant the token
  `PVEAuditor` role on `/`.

### Run it (compose snippet - add to `docker-compose.yml`)

```yaml
  pve-exporter:
    image: prompt/prometheus-pve-exporter:3.4.4   # verify current tag on the project's registry
    container_name: pve-exporter
    restart: unless-stopped
    environment:
      - PVE_USER=root@pam
      - PVE_TOKEN_NAME=prometheus
      - PVE_TOKEN_VALUE=<the-token-secret>
      - PVE_VERIFY_SSL=false
    ports:
      - "9221:9221"
    networks: [monitoring]
```

(The project is `github.com/prometheus-pve/prometheus-pve-exporter`; it also
installs via `pip install prometheus-pve-exporter` if you'd rather run it as a
systemd service on the PVE host.)

### Prometheus job (multi-target exporter pattern)

The exporter is queried with the **Proxmox node's** address as a `target`
parameter - like blackbox-exporter. Uncomment the `proxmox` job in
`prometheus/prometheus.yml`:

```yaml
  - job_name: proxmox
    metrics_path: /pve
    params: { module: [default] }
    static_configs:
      - targets: ["10.0.0.10"]        # PVE node IP(s), NOT the exporter
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: pve-exporter:9221
```

### Useful pve-exporter series

- `pve_up{id="lxc/101"}` - is the guest running (1/0)
- `pve_cpu_usage_ratio{id="lxc/101"}` / `pve_memory_usage_bytes` /
  `pve_memory_size_bytes`
- `pve_disk_usage_bytes` / `pve_disk_size_bytes` (per guest **and** per storage)
- `pve_guest_info` - name/tags/node mapping (join on `id`)
- `pve_node_info`, `pve_version_info`
- cluster: `pve_cluster_quorate`, HA status series

Dashboards: search grafana.com for "Proxmox via prometheus-pve-exporter"
(IDs **10347** and **15356** are common starting points).

---

## Putting it together

```
Proxmox host 10.0.0.10
├─ node-exporter :9100        -> node-fleet job     (host OS)
├─ pve-exporter (or on obs box) -> proxmox job       (PVE API: CT status, quotas)
├─ LXC 101 (postgres) 10.0.0.20
│   └─ node-exporter :9100    -> node-fleet job     (this CT's OS)
└─ LXC 102 (redis) 10.0.0.21
    └─ node-exporter :9100    -> node-fleet job
```

In Grafana, a `box` template variable (`label_values(node_uname_info, box)`) then
lets one dashboard cover every host and container.
