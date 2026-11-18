#!/bin/sh
set -eu
umask 077
if [ "$#" -ne 1 ]; then
    echo "Usage: sh scripts/backup.sh /private/path/campusflow.dump" >&2
    exit 2
fi
out=$1
if [ -e "$out" ]; then
    echo "Backup destination already exists" >&2
    exit 2
fi
tmp=$(mktemp "${out}.XXXXXX")
verify="campusflow_restore_$(date +%s)_$$"
created=0
cleanup() {
    if [ "$created" = 1 ]; then
        docker compose exec -T db dropdb -U campusflow "$verify" || :
    fi
    if [ -n "$tmp" ]; then rm -f -- "$tmp"; fi
}
trap cleanup EXIT
docker compose exec -T db pg_dump -U campusflow -Fc campusflow > "$tmp"
docker compose exec -T db createdb -U campusflow "$verify"
created=1
docker compose exec -T db pg_restore -U campusflow --exit-on-error -d "$verify" < "$tmp"
docker compose exec -T db psql -U campusflow -d "$verify" -v ON_ERROR_STOP=1 -qAt \
    -c 'SELECT version_num FROM alembic_version'
ln -- "$tmp" "$out"
printf '%s\n' "Verified backup: $out"
