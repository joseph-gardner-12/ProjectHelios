#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

kind=${1:-daily}
[[ "$kind" == daily || "$kind" == deploy ]] || { echo 'Use daily or deploy' >&2; exit 2; }
# Root-owned, shell-compatible assignments; never print this file or enable xtrace.
# shellcheck disable=SC1091
source /etc/helios/backend.env
export PGHOST="$POSTGRES_HOST" PGPORT="$POSTGRES_PORT" PGDATABASE="$POSTGRES_DB"
export PGUSER="$POSTGRES_USER" PGPASSWORD="$POSTGRES_PASSWORD" PGCONNECT_TIMEOUT=5
directory=/var/backups/helios/$kind
mkdir -p "$directory"
exec 9>/var/backups/helios/backup.lock
flock -w 60 9
destination="$directory/$(date -u +%Y%m%dT%H%M%S)-$$.dump"
trap 'rm -f "${destination}.partial"' EXIT
pg_dump --format=custom --no-owner --no-acl --lock-wait-timeout=5s --file="${destination}.partial"
pg_restore --list "${destination}.partial" >/dev/null
mv "${destination}.partial" "$destination"
# Keep seven completed backups in each category; failed dumps never prune good copies.
mapfile -t expired < <(find "$directory" -maxdepth 1 -name '*.dump' -type f -printf '%f\n' | sort -r | tail -n +8)
for filename in "${expired[@]}"; do rm -- "$directory/$filename"; done
echo "Backup complete: $destination"
