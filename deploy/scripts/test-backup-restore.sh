#!/bin/bash
# Exercises backup.sh and restore.sh for real against a scratch database and scratch folders.
# Needs: psql, createdb, dropdb, pg_dump, pg_restore, rsync, and PGHOST/PGUSER/PGPASSWORD set for
# a user that can create databases.   Usage:  ./scripts/test-backup-restore.sh
set -uo pipefail
HERE="$(cd "$(dirname "$0")/../backup" && pwd)"
T="$(mktemp -d)"; export DATA_DIR="$T/data" BACKUP_DIR="$T/backups" PGDATABASE=gridora_backup_test
trap 'dropdb --if-exists "$PGDATABASE" 2>/dev/null; rm -rf "$T"' EXIT
fails=0
ok()   { echo "  ok   $1"; }
bad()  { echo "  FAIL $1"; fails=$((fails + 1)); }
check(){ if eval "$2"; then ok "$1"; else bad "$1"; fi; }

dropdb --if-exists "$PGDATABASE"; createdb "$PGDATABASE"
psql -q -c "create table files (id serial primary key, storage_key text not null)"
mkdir -p "$DATA_DIR/users/u1/original" "$DATA_DIR/quarantine"
for i in 1 2 3; do
  printf 'content %s\n' "$i" > "$DATA_DIR/users/u1/original/f$i.csv"
  psql -q -c "insert into files (storage_key) values ('users/u1/original/f$i.csv')"
done
echo "half-received upload" > "$DATA_DIR/quarantine/partial"

echo "== backup"
"$HERE/backup.sh" > "$T/b1.log" 2>&1; check "first backup exits 0" '[ $? -eq 0 ]'
DUMP="$(ls "$BACKUP_DIR"/db/*.dump | head -n1)"; SNAP="$(ls -d "$BACKUP_DIR"/files/2* | head -n1)"
check "dump and snapshot exist" '[ -f "$DUMP" ] && [ -d "$SNAP" ]'
check "manifest written with checksum" 'grep -q "^dump_sha256=" "$BACKUP_DIR"/MANIFEST-*.txt'
check "quarantine is NOT in the backup" '[ ! -e "$SNAP/quarantine" ]'
check "stored files are in the snapshot" '[ "$(find "$SNAP/users" -type f | wc -l)" -eq 3 ]'
sleep 1; printf 'content 4\n' > "$DATA_DIR/users/u1/original/f4.csv"
psql -q -c "insert into files (storage_key) values ('users/u1/original/f4.csv')"
"$HERE/backup.sh" > "$T/b2.log" 2>&1; check "second backup exits 0" '[ $? -eq 0 ]'
SNAP2="$(ls -d "$BACKUP_DIR"/files/2* | tail -n1)"
check "unchanged files are hard-linked, not copied again" \
  '[ "$(stat -c %i "$SNAP/users/u1/original/f1.csv")" = "$(stat -c %i "$SNAP2/users/u1/original/f1.csv")" ]'
DUMP2="$(ls "$BACKUP_DIR"/db/*.dump | tail -n1)"

echo "== disaster, then restore"
psql -q -c "delete from files"; rm -rf "$DATA_DIR"/users
"$HERE/restore.sh" > "$T/r0.log" 2>&1; check "restore refuses without --yes" '[ $? -eq 2 ]'
"$HERE/restore.sh" --yes "$DUMP2" "$SNAP2" > "$T/r1.log" 2>&1; rc=$?
check "restore exits 0" '[ $rc -eq 0 ]'
check "database rows are back" '[ "$(psql -At -c "select count(*) from files")" = 4 ]'
check "file bytes are back and identical" '[ "$(cat "$DATA_DIR/users/u1/original/f4.csv")" = "content 4" ]'
check "restore says OK" 'grep -q "restore OK" "$T/r1.log"'

echo "== restore refuses bad input"
cp "$DUMP2" "$T/tampered.dump"; mkdir -p "$T/x/db"; cp "$DUMP2" "$T/x/db/$(basename "$DUMP2")"
cp "$BACKUP_DIR/MANIFEST-$(basename "$DUMP2" .dump | sed 's/^gridora-//').txt" "$T/x/"
printf 'X' | dd of="$T/x/db/$(basename "$DUMP2")" bs=1 seek=100 conv=notrunc 2>/dev/null
"$HERE/restore.sh" --yes "$T/x/db/$(basename "$DUMP2")" "$SNAP2" > "$T/r2.log" 2>&1
check "tampered dump is rejected by its checksum (exit 3)" '[ $? -eq 3 ] && grep -q "CHECKSUM MISMATCH" "$T/r2.log"'
rm -f "$SNAP2/users/u1/original/f2.csv"; rm -rf "$DATA_DIR"/users
"$HERE/restore.sh" --yes "$DUMP2" "$SNAP2" > "$T/r3.log" 2>&1
check "a file missing from the snapshot is reported and fails the restore (exit 4)" \
  '[ $? -eq 4 ] && grep -q "MISSING: users/u1/original/f2.csv" "$T/r3.log"'

echo "== retention"
touch -d '30 days ago' "$DUMP"; touch -d '30 days ago' "$SNAP"
"$HERE/backup.sh" > "$T/b3.log" 2>&1
check "old backups are pruned" '[ ! -f "$DUMP" ] && [ ! -d "$SNAP" ]'
check "newest backups are kept" '[ -f "$DUMP2" ] && [ -d "$SNAP2" ]'

echo; if [ "$fails" -eq 0 ]; then echo "BACKUP/RESTORE OK"; else echo "BACKUP/RESTORE FAILED: $fails"; exit 1; fi
