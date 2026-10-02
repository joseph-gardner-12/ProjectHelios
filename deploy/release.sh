#!/usr/bin/env bash
# Installed by bootstrap as a root-owned executable; runs as helios-deploy, not root.
set -Eeuo pipefail
umask 022

sha=${1:-}
checksum=${2:-}
[[ "$sha" =~ ^[0-9a-f]{40}$ && "$checksum" =~ ^[0-9a-f]{64}$ ]] || {
    echo 'Usage: helios-deploy COMMIT_SHA ARCHIVE_SHA256' >&2; exit 2;
}
[[ $(id -un) == helios-deploy ]] || { echo 'Run as helios-deploy' >&2; exit 2; }
root=/srv/helios
release="$root/releases/$sha"
archive="$root/incoming/$sha.tar.gz"
exec 9>"$root/deploy.lock"
flock -w 900 9

printf '%s  %s\n' "$checksum" "$archive" | sha256sum --check --status
set -a
# shellcheck disable=SC1091
source /etc/helios/backend.env
set +a
export UV_PYTHON_INSTALL_DIR=/opt/helios/python
export UV_CACHE_DIR=/var/cache/helios-uv
export PYTHONDONTWRITEBYTECODE=1
previous=$(readlink -f "$root/current" 2>/dev/null || true)
activated=false

healthy() {
    local expected=$1 _attempt headers
    headers=$(mktemp)
    for _attempt in {1..12}; do
        if curl --fail --silent --show-error --max-time 10 \
            --dump-header "$headers" https://api.projecthelios.dev/api/ready/ >/dev/null \
            && tr -d '\r' <"$headers" | grep -qiFx "X-Helios-Release: $expected"; then
            rm -f "$headers"
            return 0
        fi
        sleep 5
    done
    rm -f "$headers"
    return 1
}

activate() {
    ln -sfn "$1" "$root/current.next"
    mv -Tf "$root/current.next" "$root/current"
}

failed() {
    local result=$?
    trap - ERR
    if [[ "$activated" == true ]]; then
        if [[ -n "$previous" && -d "$previous" ]]; then
            echo 'Activation failed; restoring the previous code release.' >&2
            activate "$previous"
            sudo -n /usr/bin/systemctl restart helios.service || true
            healthy "$(basename "$previous")" || echo 'Previous release is also unhealthy; operator action required.' >&2
        else
            sudo -n /usr/bin/systemctl stop helios.service || true
            rm -f "$root/current"
            echo 'First deployment failed; no previous release exists.' >&2
        fi
    fi
    echo 'Deployment failed. Database migrations were NOT reversed. See the runbook.' >&2
    exit "$result"
}
trap failed ERR

if [[ "$previous" == "$release" ]]; then
    healthy "$sha"
    rm -f "$archive"
    echo "Release $sha is already active."
    exit 0
fi
if [[ -e "$release" ]]; then
    [[ -f "$release/.archive-sha256" && $(cat "$release/.archive-sha256") == "$checksum" ]]
else
    mkdir "$release"
    tar --extract --gzip --file="$archive" --directory="$release" --no-same-owner
    printf '%s\n' "$checksum" >"$release/.archive-sha256"
fi
backend="$release/apps/backend"
printf 'HELIOS_RELEASE_SHA=%s\n' "$sha" >"$release/release.env"
/opt/helios/tools/bin/uv sync --locked --no-dev --project "$backend"
python="$backend/.venv/bin/python"
"$python" "$backend/manage.py" check --deploy --fail-level WARNING
"$python" "$backend/manage.py" collectstatic --noinput
/usr/local/bin/helios-backup deploy
# Avoid waiting indefinitely for conflicting locks; do not impose a short migration runtime.
PGOPTIONS='-c lock_timeout=2000' "$python" "$backend/manage.py" migrate --noinput
activated=true
activate "$release"
sudo -n /usr/bin/systemctl restart helios.service
healthy "$sha"
touch "$release/.deployed"
# The new release is committed. Retention errors should not roll back healthy code.
activated=false
rm -f "$archive"
echo "Deployed $sha"

# Keep the current release, its immediate predecessor, and one other recent release.
kept=0
while read -r _ deployed; do
    directory=$(basename "$(dirname "$deployed")")
    [[ "$directory" =~ ^[0-9a-f]{40}$ ]] || continue
    [[ "$directory" == "$sha" ]] && continue
    if [[ "$root/releases/$directory" == "$previous" ]]; then continue; fi
    kept=$((kept + 1))
    limit=2
    if [[ -f "$previous/.deployed" ]]; then limit=1; fi
    if (( kept > limit )); then rm -rf -- "$root/releases/$directory"; fi
done < <(find "$root/releases" -mindepth 2 -maxdepth 2 -name .deployed -type f -printf '%T@ %p\n' | sort -nr)
