# Dev/test VM and budget

The user authorized Dallas (`dfw`) Linux dev/test resources on 2026-11-08, with a **$15 total spending limit**. This authorization persists for implementation; it does not authorize publication or spending above that limit.

Selected from the live Vultr API: `vc2-1c-2gb`, 1 vCPU, 2048 MiB RAM, 55 GB SSD, 2048 GB included transfer; $0.014/hour with a $10/month cap. Ubuntu 24.04 LTS x64 is OS ID 2284. No backups, snapshots, block storage, reserved IP, or paid protection were requested. Recheck availability/pricing before recreating.

The VM is ephemeral: destroy it after each implementation test session. Power-off does not stop instance storage billing. Track cumulative session cost against $15; do not interpret the monthly cap as a total lifetime cap.

Private local state, dedicated key, SSH known-hosts file, plan and logs are under ignored `runtime/dev-vm/` (0700). Do not commit or transfer that directory. Only repository-owned runtime setup and fixed probe scripts are sent to the VM; no API or model key is transferred.

Provisioning command pattern (source .env privately without tracing):

```
terraform -chdir=infra/terraform plan -input=false \
  -state=../../runtime/dev-vm/terraform.tfstate \
  -var-file=../../runtime/dev-vm/dev.tfvars \
  -var-file=../../runtime/dev-vm/key.auto.tfvars.json \
  -out=../../runtime/dev-vm/create.tfplan
terraform -chdir=infra/terraform apply -input=false \
  -state=../../runtime/dev-vm/terraform.tfstate ../../runtime/dev-vm/create.tfplan
```

Upload/run `infra/host/setup-runtime` as root after cloud-init completes. This uses the [official Docker Ubuntu apt repository](https://docs.docker.com/engine/install/ubuntu/), disables the rootful daemon, configures user namespace ranges and cgroup delegation, and installs the [rootless user service](https://docs.docker.com/engine/security/rootless/). Package versions are retained on reruns and recorded in the session evidence. New hosts resolve current packages; fully locked host releases remain M5 work.

Run `scripts/doctor` as doctor-runner with its XDG_RUNTIME_DIR, rootless DOCKER_HOST and a pre-pulled digest-pinned SIMULATION_IMAGE. It performs only fixed probes. A passing preflight is evidence for these controls, not the complete M3 containment suite.

After exporting bounded evidence, destroy this session's resources:

```
terraform -chdir=infra/terraform destroy -input=false -auto-approve \
  -state=../../runtime/dev-vm/terraform.tfstate \
  -var-file=../../runtime/dev-vm/dev.tfvars \
  -var-file=../../runtime/dev-vm/key.auto.tfvars.json
```

Verify the instance is absent from Vultr after destroy. Terraform state may contain the initial VM password: keep its directory private even after teardown.

## Spending ledger (estimates pending provider invoice)

| Session | Rate | Conservative compute estimate | Teardown verification |
|---|---|---|---|
| M0 | $0.014/hour | $0.014 (one hour) | HTTP 404 at 2026-11-08T21:36:35Z |
| M1 | $0.014/hour | $0.014 (one hour) | All six resources destroyed; HTTP 404 at 2026-11-08T22:02:11Z |

Estimated total $0.028; estimated remaining authorization $14.972. No running VM, snapshots or paid storage were retained.

M2 session: all six resources destroyed; GET returned 404 at 2026-11-08T22:26:59Z. Conservative compute estimate $0.014; recorded live inference estimate $0.00094165 (including the initial incomplete trial). Cumulative tracked M0–M2 estimate is $0.04294 plus the small unmetered M0 inference probe, pending provider billing; approximately $14.957 remains authorized. The exact trusted verifier image was exported locally before teardown; no cloud resource was retained for it.

M3 session: under one hour at $0.014/hour, zero paid inference calls. All services stopped; zero containers remained; all six resources destroyed and GET returned 404 at 2026-11-08T23:28:36Z. Cumulative tracked estimate is $0.05694 plus the small unmetered M0 inference probe, pending provider invoice; approximately $14.943 remains authorized. No VM, snapshot or paid storage remains.

M5 local-review work: the attempted fresh provision was refused by Vultr's API-key source-IP allowlist before any resource creation. Terraform state contains no resource instances. No M5 cloud spending occurred. Current deliverables are local build/container review and registry transport tooling; fresh deployment/recovery validation remains pending restored provider access. Cumulative tracked estimate remains $0.05694 plus the small unmetered M0 probe, pending provider billing.
