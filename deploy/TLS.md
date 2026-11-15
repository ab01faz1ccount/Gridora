# TLS

nginx terminates TLS (TLS 1.2 and 1.3) with `deploy/certs/tls.crt` (full chain) and `tls.key`, mounted read-only.

| Situation | What to do |
|---|---|
| Internal CA (typical) | Issue a server certificate for the host name users type, with a `subjectAltName` for that name. Put the chain in `tls.crt`. Install the CA certificate on client machines. |
| Certificate from a public CA | Same files. Renew before expiry; `docker compose restart nginx` picks up new files. |
| Local trial | `scripts/make-dev-cert.sh` (self-signed, 365 days). Browsers warn. Never use in production. |

- Cookies are `Secure` and `__Host-` prefixed: the app only works over HTTPS (the browser refuses them on plain HTTP).
- HSTS is sent (`max-age=31536000`, no `includeSubDomains`/preload). Remove the header only if you must go back to HTTP.
- The key must be readable by the nginx user inside the container (mode 644 on a private host folder, or use Docker secrets); keep the folder private on the host.
- Not verified: renewal automation, OCSP stapling, client-certificate authentication.
