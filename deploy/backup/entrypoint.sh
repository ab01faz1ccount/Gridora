#!/bin/sh
# Runs backup.sh every day at BACKUP_AT (HH:MM, container local time = UTC unless TZ is set).
set -eu
AT="${BACKUP_AT:-02:30}"
echo "backup service: daily at ${AT}, keep ${BACKUP_KEEP_DAYS:-14} days"
while true; do
  now=$(date +%s)
  target=$(date -d "$(date +%Y-%m-%d) ${AT}" +%s 2>/dev/null || date -d "${AT}" +%s)
  [ "$target" -le "$now" ] && target=$((target + 86400))
  sleep $((target - now))
  backup.sh || echo "BACKUP FAILED (see above)" >&2
done
