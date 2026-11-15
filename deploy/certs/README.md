Put the server certificate here as `tls.crt` (full chain) and the key as `tls.key`.
They are mounted read-only into nginx. Never commit them (this folder's .gitignore blocks it).
For a quick local trial: `../scripts/make-dev-cert.sh` (self-signed, NOT for production). See ../TLS.md.
