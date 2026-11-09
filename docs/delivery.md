# M5 release operations

M5 implementation is in progress. A fresh Vultr deployment, live HTTPS smoke, rollback/restart and on-host restoration must pass before marking it complete. Local tests or Docker Desktop builds do not establish the Linux rootless runtime gate.

## Release model

Caddy, API, model worker and runner remain separate systemd services and Linux identities. Only the runner reaches the dedicated rootless Docker socket. The API shares a restricted control directory with the worker; Caddy can read only static release assets. Application and candidate/verifier state are separate. No candidate code runs on the host.

The control OCI image is a **trusted release carrier**, containing application source, static web assets and hash-locked dependency wheels. Installation copies `/release` from the reviewed local image into a versioned root-owned host directory and installs wheels offline. Services run as separate host users, rather than sharing a single container identity or Docker access. The manifest pins the carrier image ID, simulation reference, verifier image ID, verification hashes, policy/schema and source Git SHA/dirty status. `images.tar.gz` transports the exact images; SHA256SUMS covers it and the manifest. Checksums need an authenticated distribution channel; they are not a signature.

Build on Linux amd64 CI or an explicitly cross-platform Docker builder. Node 24 and the configured Python environment are required. The existing lockfiles pin application dependencies; the host OS receives Ubuntu package security updates. Package versions must be captured during deployment; byte-identical OS rebuilds are not claimed.

```
make setup check web-setup web-check
make release RELEASE=v1
```

Commit changes before a release. A local test snapshot requires explicit `ED_ALLOW_DIRTY_RELEASE=1` and remains labelled dirty in reports. Artifacts go under ignored runtime/release. Current builds remain local for review. The optional GitLab registry release job is manual and restricted to protected refs; it uses per-job registry credentials and no deployment secrets. Configure the protected runner and publication environment before use. No job automatically provisions or deploys infrastructure.

## Infrastructure and access

Terraform provisions Dallas VM/key/firewall/cloud-init together. Supply validated available plan/OS IDs and restricted admin IPv4 CIDR. IPv6 is disabled; 80/443 are public and SSH is admin-only. `release_manifest_sha256` is non-secret provenance only. No cloud/inference/service key belongs in Terraform variables, state inputs or cloud-init. State may contain Vultr's initial root password: keep its directory 0700 and state/backup files 0600, outside Git; store an encrypted operator backup.

```
make infra-check
make infra-plan
make infra-apply
```

Review the saved plan before apply. Explicit provider authorization and the budget are required. Cloud-init embeds the secret-free, rerunnable runtime/control/delivery setup scripts. It installs the rootless daemon and package prerequisites but does not inject secrets or start the application. Wait for `cloud-init status --wait`, inspect its result, then rerun setup to verify idempotency. Confirm the SSH host key using the provider console or another authenticated source and add it to the operator's known_hosts; deployment refuses unknown keys.

## Configure and deploy

After choosing a hostname under your control, point its A record at the VM and ensure the provider firewall permits 80/443. Caddy manages public certificates and HTTP redirects for that hostname; see [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https). No TLS bypass or self-signed public demo is intended.

`make deploy` now creates and stages the three service environment files automatically from the local `.env` file and/or exported environment. Exported variables override the file, including empty values. The root `.env` itself is never copied or executed; only the allowlisted role settings travel over verified SSH stdin. The receiver creates `/etc/experiment-doctor` as root with mode 0700 and writes owned regular files with mode 0600:

- `api.env`: PUBLIC_ORIGIN=https://your-hostname, API_SESSION_KEY and API_ENABLE_OPERATOR_PROBES. If API_SESSION_KEY is unset/empty, staging preserves the existing remote key or generates a 32-byte random key on first deployment. An explicit nonempty key replaces it and must contain at least 32 ASCII characters. Operator probes default to 0; API_OPERATOR_TOKEN is transferred only when API_ENABLE_OPERATOR_PROBES=1 explicitly enables the supervised probe and the token is strong enough.
- `inference.env`: INFERENCE_BASE_URL=https://api.vultrinference.com/v1, validated INFERENCE_MODEL and INFERENCE_API_KEY only. Never include VULTR_API_KEY.
- `web.env`: PUBLIC_HOST=your-hostname and ACME_EMAIL=your-contact-email. These are configuration, not secrets.

Required local inputs are INFERENCE_MODEL, INFERENCE_API_KEY, ACME_EMAIL, and either PUBLIC_ORIGIN or PUBLIC_HOST. The hostname/origin is derived from whichever is provided; if both are present they must agree. Deployment accepts a public DNS hostname and HTTPS on port 443. INFERENCE_BASE_URL defaults to the fixed Vultr endpoint. VULTR_API_KEY, registry credentials, unrelated environment values and runtime socket settings are never included in the staged payload.

The installer writes runner.env from the reviewed manifest, with only image IDs and its private Docker socket/runtime directory. No service reads another role's credential file. The web proxy passes only public /api and /health routes; /execution is explicitly denied and operator routes are disabled by the backend unless separately enabled.

```
make deploy DEPLOY_HOST=root@vm-ip RELEASE_DIR=runtime/release DEPLOY_KEY=/private/path/key
# Select a different local input file:
make deploy DEPLOY_HOST=root@vm-ip RELEASE_DIR=runtime/release DEPLOY_KEY=/private/path/key DEPLOY_ENV_FILE=/private/production.env
# Ignore local files and use only exported settings:
make deploy DEPLOY_HOST=root@vm-ip RELEASE_DIR=runtime/release DEPLOY_KEY=/private/path/key DEPLOY_ENV_FILE=-
```

Validate inputs locally without displaying secrets or making a connection:

```
.venv/bin/python -m packages.delivery.configure --check
.venv/bin/python -m packages.delivery.configure --env-file /private/production.env --check
```

Staging can also run independently with `python -m packages.delivery.configure --host root@vm-ip --identity /private/path/key`, using the project's Python environment. `--known-hosts` or ED_SSH_KNOWN_HOSTS selects a dedicated verified host-key file. Settings travel only over encrypted stdin, not arguments or logs; only trusted receiver code is sent as the remote command. Files are replaced atomically, with rollback of already replaced files if a write fails, and symlink/unowned-file targets are rejected. Existing services are not restarted by standalone staging. Deployment fails before release upload/service shutdown if staging fails. The input format supports single-line KEY=value, optional export, quoted values and comments; shell commands, variable substitution and multiline values are not evaluated/supported. The local preview requires none of this remote configuration.

SSH/SCP child processes receive a minimal connection environment, excluding inherited project/cloud/registry credentials. Output files quote literal values using [systemd EnvironmentFile rules](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec#EnvironmentFile=); special characters in credentials are not evaluated as shell code.

Installation requires a manifest hash obtained through the reviewed local release. It validates values and trusted verifier hashes, installs offline into a versioned directory, stops mutation services and settles execution, then makes a consistent backup before switching the current symlink. It checks loopback readiness with the exact public Host and starts Caddy. Failed readiness attempts to restore the preceding release/image configuration. First-install failure leaves no promoted release. This is a single-VM deployment with downtime, not a rolling release. Public HTTPS smoke is a separate mandatory promotion gate.

## Live validation and promotion

With normal certificate verification enabled:

```
make smoke-live PUBLIC_ORIGIN=https://your-hostname
```

The smoke checks secure session cookies, independent healthy and live-model repair verdicts, all final check contracts, sandbox cleanup, hash-bound ZIP files and cross-session denial. Cancellation reports the actual atomic winner. Supply only the temporary API_OPERATOR_TOKEN environment to include the controlled network denial and healthy-follow-up checks. Never put tokens in URLs. A test CA may be passed with `--ca` for private TLS testing; this does not count as a public certificate.

Run the browser workflow through HTTPS and capture the actual containment moment. Restart the service stack and then reboot the VM; await readiness and repeat a healthy run. Confirm no unexpected listeners, no rootful Docker, no forbidden cross-user permissions, no remaining containers, and record installed package versions. Only after these checks promote/share the release and demo URL.

## Rollback, backup and restore

```
sudo bash /opt/experiment-doctor/current/infra/host/rollback PREVIOUS_RELEASE_ID
```

This switches only to an already installed compatible schema-v1 release and restores its image settings and units. Rerun readiness and smoke. For schema-incompatible changes, stop all services, restore the pre-release backup and corresponding code before starting. No destructive database migration is included in this version.

The operator-only `packages.delivery.backup` uses SQLite's backup API, integrity checks and a hash manifest for control/runner data and evidence. It excludes WAL/SHM/lock files and never includes /etc credentials. Service processes must be stopped before create/restore. Keep backups private and encrypted off-host. Restore preserves displaced state as `*.before-restore` and refuses to overwrite an earlier displaced copy.

```
cd /opt/experiment-doctor/current
sudo .venv/bin/python -m packages.delivery.backup create --root /var/lib/experiment-doctor --destination /private/backup
sudo .venv/bin/python -m packages.delivery.backup validate --root /var/lib/experiment-doctor --destination /private/backup
sudo .venv/bin/python -m packages.delivery.backup restore --root /var/lib/experiment-doctor --destination /private/backup
```

Test a round trip on disposable data and on the deployment before claiming recovery. Backups contain session/report data and are never public release artifacts. Retention uses the existing 24-hour janitor, preserving active jobs; do not implement demo reset by deleting active state. Stop services and export needed evidence before an intentional reset or teardown.

Destroy temporary resources explicitly with `make infra-destroy`, verify the instance is absent, and update the budget ledger. Power-off does not terminate billing. Retaining a public demo needs an agreed lifetime within the remaining authorization.

`make release-check` verifies the exported hash-locked wheel requirements still match uv.lock. The installer records installed bytes; `infra/host/promote-release REVIEWED_SMOKE_JSON` is a separate gate requiring a clean release and real HTTPS repair, healthy, containment, cancellation and integrity/ownership results. Complete the documented recovery checks before invoking it. A dirty local snapshot is deliberately ineligible for promotion.

Deployment remains an explicit operator CLI action from reviewed local artifacts. No GitHub publication or deployment workflow is included. `ED_SSH_KNOWN_HOSTS` can select a dedicated verified host-key file for `scripts/deploy`; infrastructure apply remains separate from release installation.

The manifest identifies control schema 1, runner schema 2 (including the M3 security-event migration), and diagnosis schema 1 separately. `sudo .venv/bin/python -m packages.delivery.status` prints bounded JSON counts for queue/outcome/job reasons/cleanup, worker heartbeat and free disk. Combine these with `/health/ready` and systemd state for the single-VM operator snapshot; prompts, credential values and session IDs are excluded. Existing SQLite journals retain experiment/job/attempt tool IDs and enforcement events. No hosted monitoring service or automated public alerting is claimed.

## Local container and registry review

The requested local hostname is **experiment-doctor.local**. Add `127.0.0.1 experiment-doctor.local` to the Mac's `/etc/hosts` if it is not already present. Start a local API with that exact origin; for the explicit offline review fixture:

```
ED_BROWSER_ORIGIN=http://experiment-doctor.local:8080 .venv/bin/python -m tests.browser_server
make web-container
```

Open http://experiment-doctor.local:8080. The web container is non-root, read-only, drops all capabilities, publishes only loopback port 8080 and receives no service credentials or Docker socket. It forwards API calls to the host's loopback API using Docker Desktop's host gateway. This local-only HTTP mode accepts the fixed alias only with the API's explicit local-development flag; public deployment still requires HTTPS. The offline server visibly labels the UI and reports, evaluates fixed numeric fixtures and never executes candidate code. It is not part of production images. Stop the disposable preview with `docker compose --env-file /dev/null -p experiment-doctor-preview -f compose.local.yml down` and stop the test server. The Make target uses the same dedicated project name and bypasses the private root .env.

Artifacts are built **locally for review**, with no registry push as part of build. The four-image manifest now includes control, web, verifier and simulation. The local web image is also independently runnable. `packages.delivery.registry` provides a separate explicit push command and a digest-verified pull/re-export command:

```
# After reviewing a clean release and authenticating Docker separately:
make push-release RELEASE_DIR=runtime/release REGISTRY_PREFIX=docker.io/YOUR_NAMESPACE/experiment-doctor
# GitLab uses the same command with REGISTRY_PREFIX=$CI_REGISTRY_IMAGE.
# To inspect names without contacting a registry:
.venv/bin/python -m packages.delivery.registry push --manifest runtime/release/release.json --prefix docker.io/YOUR_NAMESPACE/experiment-doctor --dry-run
# Download an approved registry transport and recreate the deployable offline archive:
.venv/bin/python -m packages.delivery.registry pull --transport registry.json --manifest-sha256 REVIEWED_SHA256 --output runtime/pulled-release
```

Use lowercase registry repository paths. Docker Hub names use `namespace/experiment-doctor-control`, `-web`, `-verifier`, `-simulation`; GitLab uses its project's nested `/control`, `/web`, `/verifier`, `/simulation` paths. Push resolves immutable registry digests and writes registry.json; pull checks the independently reviewed release manifest and every image's local identity. Mirrored simulation bytes are additionally bound to the original pinned Python image. The transport never contains credentials. Dirty development snapshots require explicit `--allow-dirty` even for a naming dry-run and cannot be promoted.

The root `.gitlab-ci.yml` runs only on protected refs using a dedicated protected Linux amd64 shell runner tagged `experiment-doctor-builder`, with Python 3.12, uv 0.9.8, Node 24, make and a trusted-build Docker daemon already installed. Its manual release job builds, authenticates using per-job CI_REGISTRY_USER/CI_REGISTRY_PASSWORD, pushes only to CI_REGISTRY_IMAGE, and preserves release.json/registry.json as artifacts. Configure the registry-publication environment and protected runner in GitLab before use. [GitLab documents these per-job registry credentials](https://docs.gitlab.com/user/packages/container_registry/authenticate_with_container_registry/). No cloud or inference key enters CI, and no pipeline has been dispatched during implementation. Local Docker Hub authentication remains a separate operator action.

To run the named-container browser checks after starting the preview API and web container: `cd apps/web && npx playwright test --config playwright.container.config.ts`. They use isolated Chrome profiles and include a hostname resolver mapping, so they do not modify system DNS. The ordinary browser suite can use `ED_BROWSER_PORT=8100 npm run test:e2e` to avoid interrupting the preview's API on port 8000. Local named HTTP integrity checks use pinned @noble/hashes SHA-256; native secure-context Web Crypto is not required.
