#!/bin/sh
# One backup = a Postgres dump + a hard-link snapshot of the stored files.
# Order: DATABASE FIRST, then files. Stored files are immutable and only ever added (deletes are
# user-requested), so every file the dump references is in the snapshot unless it was deleted in
# the seconds between the two steps; restore.sh reports any such file instead of hiding it.
set -eu
DATA_DIR="${DATA_DIR:-/data}"
BACKUP_DIR="${BACKUP_DIR:-/backups}"
KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DB_DIR="$BACKUP_DIR/db"; FILES_DIR="$BACKUP_DIR/files"
mkdir -p "$DB_DIR" "$FILES_DIR"

log() { echo "$(date -u +%FT%TZ) backup: $*"; }

DUMP="$DB_DIR/gridora-$STAMP.dump"
log "dumping database to $(basename "$DUMP")"
pg_dump --format=custom --no-owner --file="$DUMP.partial"
mv "$DUMP.partial" "$DUMP"

PREV="$(ls -1d "$FILES_DIR"/2* 2>/dev/null | tail -n 1 || true)"
SNAP="$FILES_DIR/$STAMP"
log "snapshotting files from $DATA_DIR (${PREV:+hard-linking unchanged files against $(basename "$PREV")})"
mkdir -p "$SNAP.partial"
# quarantine/ holds half-received uploads: never part of a backup.
rsync -a --exclude 'quarantine/' ${PREV:+--link-dest="$PREV"} "$DATA_DIR"/ "$SNAP.partial"/
mv "$SNAP.partial" "$SNAP"

(
  cd "$BACKUP_DIR"
  {
    echo "created_utc=$STAMP"
    echo "dump=db/gridora-$STAMP.dump"
    echo "dump_sha256=$(sha256sum "db/gridora-$STAMP.dump" | cut -d' ' -f1)"
    echo "snapshot=files/$STAMP"
    echo "files_in_snapshot=$(find "files/$STAMP" -type f | wc -l | tr -d ' ')"
  } > "MANIFEST-$STAMP.txt"
)

# Retention: remove whole backups older than KEEP_DAYS (never the newest one).
log "pruning backups older than $KEEP_DAYS days"
find "$DB_DIR" -name 'gridora-*.dump' -mtime +"$KEEP_DAYS" ! -newer "$DUMP" -delete
find "$FILES_DIR" -mindepth 1 -maxdepth 1 -type d -mtime +"$KEEP_DAYS" ! -name "$STAMP" -exec rm -rf {} +
find "$BACKUP_DIR" -maxdepth 1 -name 'MANIFEST-*.txt' -mtime +"$KEEP_DAYS" -delete
log "done: $STAMP"
