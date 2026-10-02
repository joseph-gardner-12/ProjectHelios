#!/usr/bin/env bash
# Run deliberately on a dedicated, fresh Ubuntu 24.04 Droplet as root.
set -Eeuo pipefail
umask 022
[[ $(id -u) == 0 ]] || { echo 'Run as root' >&2; exit 2; }
# shellcheck disable=SC1091
source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]] || {
    echo 'This bootstrap targets Ubuntu 24.04 only.' >&2; exit 2;
}
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y ca-certificates curl python3-venv postgresql postgresql-client \
    redis-server caddy openssl sudo util-linux unattended-upgrades

id helios-deploy >/dev/null 2>&1 || useradd --create-home --shell /bin/bash helios-deploy
id helios-app >/dev/null 2>&1 || useradd --system --user-group --no-create-home --shell /usr/sbin/nologin helios-app
install -d -o helios-deploy -g helios-deploy -m 0755 /srv/helios /srv/helios/releases
install -d -o helios-deploy -g helios-deploy -m 0700 /srv/helios/incoming /var/backups/helios
install -d -o helios-deploy -g helios-deploy -m 0755 /opt/helios/python
install -d -o helios-deploy -g helios-deploy -m 0700 /var/cache/helios-uv
install -d -o helios-deploy -g helios-deploy -m 0700 /home/helios-deploy/.ssh
touch /home/helios-deploy/.ssh/authorized_keys
chown helios-deploy:helios-deploy /home/helios-deploy/.ssh/authorized_keys
chmod 0600 /home/helios-deploy/.ssh/authorized_keys
install -d -o root -g helios-deploy -m 0750 /etc/helios

# runuser preserves the current directory. Leave root's private working directory
# before running uv or PostgreSQL commands under their service accounts.
cd /srv/helios
python3 -m venv /opt/helios/tools
/opt/helios/tools/bin/pip install --disable-pip-version-check 'uv==0.11.16'
runuser -u helios-deploy -- env UV_PYTHON_INSTALL_DIR=/opt/helios/python \
    UV_CACHE_DIR=/var/cache/helios-uv /opt/helios/tools/bin/uv --no-config python install 3.14

systemctl enable --now postgresql redis-server
if [[ ! -e /etc/helios/backend.env ]]; then
    if [[ $(runuser -u postgres -- psql -Atqc "SELECT 1 FROM pg_roles WHERE rolname='helios'") == 1 ]]; then
        echo 'Existing helios role found without backend.env; restore its credentials before rerunning.' >&2
        exit 1
    fi
    secret=$(openssl rand -hex 48)
    password=$(openssl rand -hex 32)
    temporary=$(mktemp /etc/helios/backend.env.XXXXXX)
    chmod 0640 "$temporary"
    chown root:helios-deploy "$temporary"
    cat >"$temporary" <<EOF
DJANGO_SETTINGS_MODULE=config.settings.production
DJANGO_SECRET_KEY=$secret
DJANGO_ALLOWED_HOSTS=api.projecthelios.dev
DJANGO_FRONTEND_ORIGINS=https://www.projecthelios.dev,https://projecthelios.dev
POSTGRES_HOST=127.0.0.1
POSTGRES_PORT=5432
POSTGRES_DB=helios
POSTGRES_USER=helios
POSTGRES_PASSWORD=$password
REDIS_URL=redis://127.0.0.1:6379/0
EOF
    mv "$temporary" /etc/helios/backend.env
fi
set -a
# shellcheck disable=SC1091
source /etc/helios/backend.env
set +a
# The installer owns the dedicated helios role/database only; existing passwords stay unchanged.
runuser -u postgres -- psql -v ON_ERROR_STOP=1 -q <<'SQL'
\getenv role_password POSTGRES_PASSWORD
SELECT format('CREATE ROLE helios LOGIN PASSWORD %L', :'role_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'helios') \gexec
SELECT 'CREATE DATABASE helios OWNER helios'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'helios') \gexec
ALTER SYSTEM SET listen_addresses = 'localhost';
ALTER SYSTEM SET shared_buffers = '64MB';
ALTER SYSTEM SET max_connections = '30';
SQL
systemctl restart postgresql
PGPASSWORD="$POSTGRES_PASSWORD" psql -h 127.0.0.1 -U helios -d helios -v ON_ERROR_STOP=1 -c 'SELECT 1' >/dev/null

# Redis only distributes transient events. Appending one include keeps reruns idempotent.
cat >/etc/redis/helios.conf <<'EOF'
bind 127.0.0.1 ::1
protected-mode yes
maxmemory 64mb
maxmemory-policy noeviction
save ""
appendonly no
EOF
if ! grep -qxF 'include /etc/redis/helios.conf' /etc/redis/redis.conf; then
    printf '\ninclude /etc/redis/helios.conf\n' >>/etc/redis/redis.conf
fi
systemctl restart redis-server

install -o root -g root -m 0755 "$source_dir/release.sh" /usr/local/bin/helios-deploy
install -o root -g root -m 0755 "$source_dir/backup.sh" /usr/local/bin/helios-backup
cat >/etc/sudoers.d/helios-deploy <<'EOF'
helios-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl restart helios.service, /usr/bin/systemctl stop helios.service
EOF
chmod 0440 /etc/sudoers.d/helios-deploy
visudo -cf /etc/sudoers.d/helios-deploy
install -m 0644 "$source_dir/helios.service" /etc/systemd/system/helios.service
install -m 0644 "$source_dir/helios-control.service" /etc/systemd/system/helios-control.service
install -m 0644 "$source_dir/helios-backup.service" /etc/systemd/system/helios-backup.service
install -m 0644 "$source_dir/helios-backup.timer" /etc/systemd/system/helios-backup.timer

# Preserve an operator-modified Caddyfile on rerun. The first install replaces the stock welcome site.
if [[ ! -f /etc/helios/caddy-installed ]]; then
    cp -a /etc/caddy/Caddyfile /etc/caddy/Caddyfile.before-helios
    install -m 0644 "$source_dir/Caddyfile" /etc/caddy/Caddyfile
    touch /etc/helios/caddy-installed
fi
caddy validate --config /etc/caddy/Caddyfile
systemctl enable --now caddy
systemctl reload caddy
install -d /etc/systemd/journald.conf.d
cat >/etc/systemd/journald.conf.d/helios.conf <<'EOF'
[Journal]
SystemMaxUse=200M
RuntimeMaxUse=50M
MaxRetentionSec=7day
EOF
systemctl restart systemd-journald
systemctl daemon-reload
systemctl enable helios.service helios-control.service
systemctl enable --now helios-backup.timer
echo 'Bootstrap complete. Add the deployment public key, configure DNS and GitHub secrets, then deploy.'
echo 'The backend starts after the first successful release. Existing secrets and data were preserved.'
