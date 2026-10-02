# Backend setup and operations

The production target is one Ubuntu 24.04 DigitalOcean Droplet at
`api.projecthelios.dev`. Vercel continues to host the frontend. See
[ADR-0002](adr/0002-digitalocean-backend-foundation.md) for decisions and the current
handoff checkpoint. These instructions provision the backend foundation; device
authentication, telemetry, commands, and frontend API integration come later.

## 1. Commit the implementation to GitHub

Review and commit this change, then push it to `main`. The workflow runs backend
checks and then attempts deployment. Until the server and secrets are configured,
the deploy job will fail with a setup message; no existing service is changed.
After setup, use **Actions → Backend checks and deployment → Run workflow → main**.

Backend code, `deploy/`, workflow, and root package changes trigger automatic
deployment. Documentation-only pushes do not. CI deploys the tested commit, not
whatever happens to be checked out on the server. An obsolete queued deployment
is skipped if `main` has advanced; run the workflow on current `main` if necessary.

## 2. Create personal and deployment SSH keys on your Mac

Reuse your personal key if you already created it. Otherwise:

```sh
ssh-keygen -t ed25519 -C helios-mac -f ~/.ssh/helios_ed25519
pbcopy < ~/.ssh/helios_ed25519.pub
```

Use a passphrase for the personal key and upload its **public** `.pub` file when
creating the Droplet. Do not overwrite an existing key.

Create a separate key for GitHub Actions. It needs no passphrase for unattended
deployment and will only be authorized for the deployment account:

```sh
ssh-keygen -t ed25519 -C helios-github-actions -f ~/.ssh/helios_actions_ed25519 -N ''
```

Keep the personal private key on your Mac. The Actions private key goes only into
the GitHub Actions secret described below; neither belongs in the repository.

## 3. Create the Droplet and firewall

In DigitalOcean, create a Project Helios project and an Ubuntu **24.04 LTS** Basic
Regular Droplet with **1 GiB RAM / 1 vCPU**, initially about **$6/month** compute.
Choose a nearby region, select your personal SSH key, enable monitoring, and
choose backups according to your budget. Database/Redis memory is kept modest;
upgrade to 2 GiB if monitoring shows memory pressure.

Attach a DigitalOcean cloud firewall:

| Direction | Rule |
| --- | --- |
| Inbound | TCP 80 and 443 from all IPv4/IPv6 addresses |
| Inbound | TCP 22 from all IPv4/IPv6 addresses, with key-only SSH |
| Outbound | Allow traffic (package downloads, DNS, TLS issuance, health checks) |

GitHub-hosted runners use changing source IPs. Restricting SSH to your Mac's IP
alone blocks Actions. This initial setup uses public port 22 with key-only access;
a runner with fixed egress or a private network is a future alternative. Never
open ports 8000, 5432, or 6379 publicly.

On your Mac, set the IP and connect:

```sh
HELIOS_IP=YOUR_DROPLET_IPV4
ssh -i ~/.ssh/helios_ed25519 root@"$HELIOS_IP"
```

Verify the server host-key fingerprint through the DigitalOcean console before
trusting the first connection. Keep this session open until a second key-based
login works.

## 4. Point the API domain at the server

At the existing DNS provider, add an `A` record for `api.projecthelios.dev` pointing
to the Droplet IPv4 address. Remove any conflicting `api` records. Add an `AAAA`
record only if IPv6 is configured and reachable. Leave the frontend's apex and
`www` records on Vercel. Use DNS-only mode if your DNS provider offers a proxy.

Caddy issues the certificate once DNS and ports 80/443 are ready. Initial requests
can return 502 until the first application release starts.

## 5. Bootstrap the server

From the repository on your Mac, upload the reviewed deployment assets:

```sh
ssh -i ~/.ssh/helios_ed25519 root@"$HELIOS_IP" 'mkdir -p /root/helios-bootstrap'
scp -i ~/.ssh/helios_ed25519 -r deploy root@"$HELIOS_IP":/root/helios-bootstrap/
ssh -i ~/.ssh/helios_ed25519 root@"$HELIOS_IP" 'bash /root/helios-bootstrap/deploy/bootstrap.sh'
```

Bootstrap installs PostgreSQL 16 (Ubuntu's package), Redis, Caddy, uv 0.11.16,
Python 3.14, two service users, release/backup scripts, and systemd units. It creates
the `helios` PostgreSQL role/database and generates secrets on the server. It does
not print those secrets. Reruns retain the environment file, database, SSH keys,
and operator-modified Caddy configuration; service units and helper scripts are
updated from the uploaded assets. Run only on a **dedicated Helios Droplet**:
bootstrap tunes PostgreSQL and Redis for this server and restarts them.

The backend unit is enabled but starts only after the first release. A daily backup
timer is enabled. The runtime user cannot write application files. The deployment
user can install code, access its database credentials, and restart/stop only the
Helios service through sudo; it does not have unrestricted root sudo.

Production settings live in `/etc/helios/backend.env` (root-owned, readable by the
deployment group). Defaults match this runbook. If editing it, use simple
`KEY=value` lines compatible with both Bash and systemd; quote literal values when
needed, with no `export`, substitutions, or executable shell commands. Never
commit, paste into chat, or print the environment file into build logs.

HSTS initially lasts one hour and applies only to the API host. The deployment
check explicitly exempts Django's subdomain/preload recommendations (W005/W021)
because neither is an initial domain-wide commitment; other warnings fail deployment.

## 6. Authorize the deployment key and enforce key-only SSH

From your Mac, append only the Actions public key to the deployment account:

```sh
cat ~/.ssh/helios_actions_ed25519.pub | ssh -i ~/.ssh/helios_ed25519 root@"$HELIOS_IP" \
  'read -r key; printf "restrict %s\n" "$key" >> /home/helios-deploy/.ssh/authorized_keys'
ssh -i ~/.ssh/helios_actions_ed25519 helios-deploy@"$HELIOS_IP" 'id -un'
```

The second command must print `helios-deploy`. The `restrict` key option disables
forwarding and PTY access while allowing deployment commands and SCP/SFTP.

In your root SSH session, enforce key-only authentication **after testing both keys**:

```sh
cat >/etc/ssh/sshd_config.d/00-helios-keys.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
EOF
sshd -t
systemctl reload ssh
```

Verify another personal-key login before closing the original session. The root
key remains the administrative recovery path; routine deployments use the limited
deployment account.

## 7. Add four GitHub Production environment secrets

Open **GitHub → repository Settings → Environments → Production → Environment
secrets → Add environment secret**. Create the `Production` environment if it
does not exist. The deployment job explicitly selects this environment so it can
access these secrets; the check job does not receive them.

| Secret | Value |
| --- | --- |
| `DEPLOY_HOST` | Droplet IPv4 address, without `https://` |
| `DEPLOY_USER` | `helios-deploy` |
| `DEPLOY_SSH_KEY` | Complete Actions private key, including BEGIN/END lines |
| `DEPLOY_KNOWN_HOSTS` | Verified server host-key line, as described below |

Copy the Actions private key into your clipboard locally, then paste it directly
into the secret field:

```sh
pbcopy < ~/.ssh/helios_actions_ed25519
```

For `DEPLOY_KNOWN_HOSTS`, run this in the trusted root session, replacing the IP:

```sh
awk '{print "YOUR_DROPLET_IPV4 " $1 " " $2}' /etc/ssh/ssh_host_ed25519_key.pub
```

Copy that public line into the secret. Do not trust an unauthenticated
`ssh-keyscan` result without verifying its fingerprint. Changing the server's host
key later requires updating this secret deliberately. GitHub needs no DigitalOcean
API token, database password, or Django secret.

If deployment says `DEPLOY_HOST is unavailable`, confirm that the secret is in
the `Production` environment's **secrets**, not its variables, and that the
workflow on `main` declares `environment: Production` on the deploy job. If it
reports an invalid format, save only the IPv4 address or hostname without a URL,
port, spaces, or trailing newline. After a workflow edit, start a new run on the
updated `main`; rerunning an old failed run uses its old workflow revision.

## 8. Deploy and verify

Run **Actions → Backend checks and deployment → Run workflow → main**. CI tests
against temporary PostgreSQL/Redis services. Deployment installs the tested commit,
checks production settings, collects static files, backs up the database, applies
migrations, switches the active release, and restarts Django. Readiness must return
the expected commit in `X-Helios-Release` over HTTPS.

From your Mac:

```sh
curl --fail https://api.projecthelios.dev/api/health/
curl --fail --include https://api.projecthelios.dev/api/ready/
```

Expected bodies are `{"status":"ok","service":"project-helios-backend"}` and
`{"status":"ok"}`. Visit `https://api.projecthelios.dev/admin/` and confirm its
stylesheet loads. The public website's simulated control screen is unchanged.

Create an admin interactively from the root session:

```sh
sudo -iu helios-deploy bash -c 'set -a; source /etc/helios/backend.env; set +a; /srv/helios/current/apps/backend/.venv/bin/python /srv/helios/current/apps/backend/manage.py createsuperuser'
```

Inspect logs/status as root:

```sh
systemctl status helios caddy postgresql redis-server --no-pager
journalctl -u helios -n 100 --no-pager
systemctl list-timers helios-backup.timer
```

Reboot the Droplet when ready, repeat both HTTP checks, and confirm the admin
account remains. Record the deployed commit, date, and verified results in ADR-0002.

## 9. Back up off-server and test a restore

Daily backups run at approximately 03:15 UTC. Seven daily and seven pre-deployment
custom-format dumps are kept under `/var/backups/helios/{daily,deploy}`. Failed dumps
do not prune good copies. They include database contents, not runtime secrets.
DigitalOcean backups are separately configured and billed.

Make a backup immediately, then copy backups to your Mac or another secure
off-server destination (run the SCP command on your Mac):

```sh
# On the Droplet as root:
sudo -u helios-deploy /usr/local/bin/helios-backup daily
# On your Mac:
mkdir -p ~/helios-backups
scp -i ~/.ssh/helios_ed25519 -r root@"$HELIOS_IP":/var/backups/helios/daily ~/helios-backups/
```

Schedule an off-server copy appropriate to your backup destination. Protect these
copies as application data, and separately retain the server environment file in
a secure secret backup. Local dumps alone cannot recover a lost Droplet.

For a non-destructive restore test, choose a completed dump and restore into a
new, disposable database as root on the Droplet:

```sh
# Replace the filename; never target the live helios database for a test.
cp /var/backups/helios/daily/CHOSEN_BACKUP.dump /tmp/helios-restore-check.dump
chown postgres:postgres /tmp/helios-restore-check.dump
chmod 600 /tmp/helios-restore-check.dump
sudo -u postgres createdb helios_restore_check
sudo -u postgres pg_restore --exit-on-error --no-owner --no-acl \
  --dbname=helios_restore_check /tmp/helios-restore-check.dump
sudo -u postgres psql -d helios_restore_check -c 'SELECT count(*) FROM django_migrations;'
sudo -u postgres dropdb helios_restore_check
rm /tmp/helios-restore-check.dump
```

## Local development and integration checks

`pnpm setup` and `pnpm dev` still use SQLite without external services. Health
returns 200; readiness deliberately returns 503 without Redis configured. `.env`
files are not implicitly loaded by Django. Use uv's explicit loader when opting in:

```sh
cp apps/backend/.env.example apps/backend/.env
# Edit credentials for your own local PostgreSQL database and Redis service.
uv run --locked --env-file apps/backend/.env --project apps/backend \
  python apps/backend/manage.py migrate
uv run --locked --env-file apps/backend/.env --project apps/backend \
  python apps/backend/manage.py runserver 127.0.0.1:8000
```

On macOS, PostgreSQL 16 and Redis can be installed/run with Homebrew. Choose unused
ports and a dedicated `helios` database/role if other projects already use them;
do not change another project's services or credentials. The local test role needs
`CREATEDB` because Django creates and destroys a separate `test_helios` database.
The production role deliberately does not have this privilege.

```sh
HELIOS_INTEGRATION_TESTS=1 uv run --locked --env-file apps/backend/.env --project apps/backend \
  python apps/backend/manage.py test apps/backend --settings=config.settings.test
```

Default `pnpm test:backend` runs local tests and skips the two external-service
integration cases unless explicitly enabled. Real Redis tests use a dedicated
channel prefix/group and clean up their subscription; use a disposable Redis
instance/database rather than sharing production.

## Failures, rollback, and maintenance

An installation/check/backup failure leaves the active release untouched. A
migration failure also leaves the previous code active, but earlier migrations may
already have committed. A post-activation failure restores the previous code and
checks its readiness; a failed first deployment stops the service. Every failure
marks Actions failed. Database migrations are **never** automatically reversed.

Changes must keep the previous application compatible with the migrated schema.
For destructive schema changes, plan staged migrations and a maintenance/recovery
procedure first. A code rollback cannot undo changed or deleted data.

For manual code rollback as root, choose a retained successful commit and take the
same deployment lock so Actions cannot race the change:

```sh
ROLLBACK_SHA=REPLACE_WITH_RETAINED_40_CHARACTER_SHA
test -f "/srv/helios/releases/$ROLLBACK_SHA/.deployed"
(
  flock -w 900 9
  ln -sfn "/srv/helios/releases/$ROLLBACK_SHA" /srv/helios/current.next
  mv -Tf /srv/helios/current.next /srv/helios/current
  systemctl restart helios
  curl --fail --include https://api.projecthelios.dev/api/ready/
) 9>/srv/helios/deploy.lock
```

Confirm the readiness header matches the rollback commit. Pause further pushes
while investigating. To redeploy current `main`, rerun its workflow. If a failed
archive extraction left an incomplete inactive release, remove only that failed
directory after verifying it is not the target of `current`, then retry. Release
retention prunes successful inactive releases only; failed releases may require
manual cleanup. Watch available disk and memory through DigitalOcean monitoring.

Changes under `deploy/` are versioned but **root-owned helpers, systemd units, and
Caddy configuration are not replaced by an unprivileged code deployment**. Upload
the reviewed assets and rerun bootstrap during maintenance; review/apply Caddy
changes manually after the first install, then validate/reload it. Restart Django
after runtime environment or unit changes. Check Ubuntu security updates and
reboot requirements regularly. No full-rate telemetry or uploaded media retention
is implemented in this foundation.

References: [Django deployment checklist](https://docs.djangoproject.com/en/6.0/howto/deployment/checklist/),
[Channels deployment](https://channels.readthedocs.io/en/stable/deploying.html),
[GitHub deployment concurrency](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/control-deployments),
[DigitalOcean pricing](https://www.digitalocean.com/pricing/droplets).
