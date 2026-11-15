# Build context: repository root.
FROM postgres:16-alpine
RUN apk add --no-cache rsync tzdata \
    && adduser -D -u 10001 gridora \
    && mkdir -p /backups && chown 10001:10001 /backups
COPY deploy/backup/backup.sh deploy/backup/restore.sh deploy/backup/entrypoint.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/backup.sh /usr/local/bin/restore.sh /usr/local/bin/entrypoint.sh
USER 10001
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
