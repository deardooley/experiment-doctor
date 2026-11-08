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
