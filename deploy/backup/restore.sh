#!/bin/sh
# Restore a backup made by backup.sh.
#   docker compose stop api nginx
#   docker compose run --rm --no-deps backup restore.sh --yes /backups/db/gridora-<stamp>.dump /backups/files/<stamp>
#   docker compose up -d
# Needs PGHOST/PGUSER/PGPASSWORD/PGDATABASE (set for the backup service). The target database is
# REPLACED by the dump. Files are copied in ADDITIVELY (nothing already in /data is deleted).
set -eu
[ "${1:-}" = "--yes" ] || { echo "refusing: pass --yes to confirm that the database will be replaced" >&2; exit 2; }
DUMP="${2:?usage: restore.sh --yes <dump file> <files snapshot dir>}"
SNAP="${3:?usage: restore.sh --yes <dump file> <files snapshot dir>}"
DATA_DIR="${DATA_DIR:-/data}"
[ -f "$DUMP" ] || { echo "no such dump: $DUMP" >&2; exit 2; }
[ -d "$SNAP" ] || { echo "no such snapshot: $SNAP" >&2; exit 2; }

MAN="$(dirname "$(dirname "$DUMP")")/MANIFEST-$(basename "$DUMP" .dump | sed 's/^gridora-//').txt"
if [ -f "$MAN" ]; then
  want="$(sed -n 's/^dump_sha256=//p' "$MAN")"
  have="$(sha256sum "$DUMP" | cut -d' ' -f1)"
  [ "$want" = "$have" ] || { echo "CHECKSUM MISMATCH: the dump differs from its manifest; not restoring" >&2; exit 3; }
  echo "dump checksum OK"
else
  echo "warning: no manifest found next to the dump; checksum not verified" >&2
fi

echo "restoring database..."
pg_restore --clean --if-exists --no-owner --dbname="$PGDATABASE" "$DUMP"

echo "restoring files (additive)..."
rsync -a "$SNAP"/ "$DATA_DIR"/

echo "verifying that every stored file the database points to exists..."
missing=0
for key in $(psql -At -c "select storage_key from files"); do
  [ -f "$DATA_DIR/$key" ] || { echo "MISSING: $key" >&2; missing=$((missing + 1)); }
done
total="$(psql -At -c "select count(*) from files")"
echo "files in database: $total, missing on disk: $missing"
[ "$missing" -eq 0 ] || { echo "restore finished WITH MISSING FILES (listed above)" >&2; exit 4; }
echo "restore OK"
