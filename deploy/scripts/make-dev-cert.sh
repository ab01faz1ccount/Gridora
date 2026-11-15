#!/bin/sh
# Self-signed certificate for local trials only (browsers will warn).
set -eu
cd "$(dirname "$0")/../certs"
openssl req -x509 -newkey rsa:2048 -nodes -days 365 -keyout tls.key -out tls.crt \
  -subj "/CN=localhost" -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
chmod 600 tls.key
echo "wrote deploy/certs/tls.crt and tls.key (self-signed, valid 365 days)"
