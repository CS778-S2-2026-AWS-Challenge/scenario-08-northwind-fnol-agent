# Deploy the Northwind self-hosted runner

This runbook is for the administrator who has `sudo` access to the Tailscale
host `secondbreakfast` (`100.71.25.5`). It installs a repository-scoped GitHub
Actions runner for the Northwind backend quality job. It does not install or
change the Qwen service, Tailscale policy, firewall rules, SSH policy, GitHub
secrets, or repository rulesets.

The runner is optional. The repository remains on `ubuntu-latest` until the
administrator completes the verification and a maintainer sets the repository
variable `NORTHWIND_CI_RUNNER=northwind-ci`.

## 1. Confirm the host and scope

Run these read-only commands on `secondbreakfast`:

```bash
hostname -f
uname -m
. /etc/os-release && printf '%s %s\n' "$ID" "$VERSION_ID"
tailscale ip -4
python3 --version
node --version
curl --fail --silent --show-error --max-time 10 --head https://github.com >/dev/null
```

Expected results are Ubuntu 24.04, `x86_64` or `aarch64`, Python 3.12, Node.js
22, an active Tailscale IPv4 address, and successful GitHub HTTPS egress. The
repository baseline needs Python 3.12 and Node.js 22; do not silently accept a
different runtime and hope the workflow still behaves the same.

## 2. Obtain the runner material

On the repository page, open **Settings > Actions > Runners > New self-hosted
runner**, choose Linux and the detected architecture, and generate the
short-lived registration token. The token expires and is for registration only.

On the host, create a private staging directory and copy the prepared files
from `local/self-hosted-runner/` into it using your approved transfer method:

```bash
sudo install -d -m 0750 -o "$USER" -g "$USER" /opt/northwind-runner-setup
```

Do not copy `.runner`, `.credentials*`, `_work`, logs, private keys, or any
`.env` file.

## 3. Install missing base packages

Only install packages that the compatibility check reports as missing. The
following command is the expected Ubuntu baseline; review it before running:

```bash
sudo apt-get update
sudo apt-get install -y --no-install-recommends \
  ca-certificates curl git jq libicu-dev python3 python3-venv tar unzip
```

Install Node.js 22 from the signed NodeSource repository if `node --version`
does not report `v22.*`. Install Python 3.12 from the host's approved Ubuntu
source if `python3 --version` is not `3.12.*`. Do not add unapproved model,
cloud, or claimant-data packages to the runner host.

## 4. Run the compatibility gate

Make the scripts executable and run the read-only check:

```bash
cd /opt/northwind-runner-setup
chmod 0750 check-compatibility.sh install-runner.sh
sudo ./check-compatibility.sh
```

If it fails, stop and fix the host. A failed check is not permission to bypass
the version, architecture, Tailscale, or GitHub egress requirement.

The optional Qwen check is disabled by default. Enable it only when explicitly
needed for a read-only connectivity check:

```bash
sudo CHECK_QWEN_HEALTH=true ./check-compatibility.sh
```

The check must not send credentials or claimant data to the model endpoint.

## 5. Verify the runner archive

Choose a pinned GitHub Actions runner release and obtain its official SHA-256
from the GitHub release page. Do not use an empty or guessed checksum. Set it
only in the current root process environment:

```bash
export RUNNER_VERSION=2.336.0
export RUNNER_SHA256='<64 hexadecimal characters from the release page>'
```

The installer downloads the matching Linux archive, verifies the checksum, and
removes its temporary download directory on exit.

## 6. Register and start the service

Run the installer as root. It creates the unprivileged `github-runner` service
account, uses `/opt/actions-runner`, registers the runner only for the
Northwind repository, and installs a systemd service. When prompted, paste the
short-lived token; input is silent and the token is not written to disk.

```bash
sudo --preserve-env=RUNNER_VERSION,RUNNER_SHA256 \
  ./install-runner.sh
unset RUNNER_VERSION RUNNER_SHA256
```

The installer must report an enabled and active service. It refuses to reuse a
non-empty installation directory that is not a valid runner installation.

## 7. Verify registration and labels

In **Settings > Actions > Runners**, confirm that the runner is online and is
repository-scoped. Its labels must include:

```text
self-hosted, Linux, X64 (or ARM64), northwind-ci, tailscale
```

On the host, verify the service without printing credentials:

```bash
cd /opt/actions-runner
sudo ./svc.sh status
sudo systemctl is-enabled "$(<.service)"
sudo systemctl is-active "$(<.service)"
```

## 8. Switch only the approved job

Do not edit workflow files on the host. After the runner is online and the
maintainer approves the switch, set the repository variable:

```text
NORTHWIND_CI_RUNNER=northwind-ci
```

The current `.github/workflows/ci.yml` uses this variable only for
`backend-quality`. Governance, audit, policy, review, Kanban, and documentation
jobs remain on hosted runners. Pull requests from forks are explicitly forced
to `ubuntu-latest`, even when the variable is set.

The first switch must be observed on a trusted same-repository branch. Confirm
the job ran on the intended runner, completed the same backend checks, and did
not expose model, cloud, or claimant data in logs.

## 9. Roll back

To return to hosted execution, remove or clear the repository variable
`NORTHWIND_CI_RUNNER`. No workflow edit is needed. Then stop the service if the
machine should no longer accept jobs:

```bash
cd /opt/actions-runner
sudo ./svc.sh stop
sudo ./svc.sh disable
```

Remove the runner from the repository **Settings > Actions > Runners** using
the repository UI. Keep `/opt/actions-runner` until the removal is confirmed;
do not delete it while a job may still be active.

## 10. Acceptance checklist

- [ ] The host is Ubuntu 24.04 with Python 3.12 and Node.js 22.
- [ ] Tailscale IPv4 and GitHub HTTPS egress checks pass.
- [ ] The runner archive checksum was obtained from the official release page.
- [ ] No token, password, private key, claimant data, or model credential was stored.
- [ ] The runner is repository-scoped and runs as `github-runner`, not root.
- [ ] The runner is online with the expected labels.
- [ ] `NORTHWIND_CI_RUNNER` was set only after the previous checks passed.
- [ ] A trusted backend job completed on the runner.
- [ ] Fork pull requests still resolve to `ubuntu-latest`.
- [ ] Rollback by clearing the repository variable has been tested or recorded.

## Ownership and boundary

The host administrator owns OS packages, systemd service state, and local
permissions. The repository maintainer owns the GitHub repository variable and
workflow switch. This runbook does not authorize changes to product code,
backend contracts, model configuration, Tailscale policy, or repository
rulesets.
