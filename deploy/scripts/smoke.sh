#!/bin/bash
# End-to-end smoke test of a RUNNING stack, over HTTPS, using only curl.
#   BASE_URL=https://localhost SMOKE_USER=admin SMOKE_PASSWORD=... CURL_OPTS=-k ./scripts/smoke.sh
# Slice covered: sign in -> workspace -> CSV upload -> import job -> workbook -> grid window.
# It cleans up after itself (deletes the workspace it creates). Exit code != 0 on any failure.
set -uo pipefail
BASE="${BASE_URL:-https://localhost}"
USER_NAME="${SMOKE_USER:?set SMOKE_USER}"
PASS="${SMOKE_PASSWORD:?set SMOKE_PASSWORD}"
HTTP_BASE="${HTTP_BASE_URL:-}"
read -r -a CURL <<< "curl -sS ${CURL_OPTS:-}"
JAR="$(mktemp)"; TMP="$(mktemp -d)"
trap 'rm -rf "$JAR" "$TMP"' EXIT
fails=0
pass() { echo "  ok   $1"; }
fail() { echo "  FAIL $1"; fails=$((fails + 1)); }
check() { if eval "$2"; then pass "$1"; else fail "$1"; fi; }
field() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p" | head -n 1; }

echo "== static app and headers"
H="$("${CURL[@]}" -D - -o "$TMP/index.html" "$BASE/")"
check "GET / is 200" 'echo "$H" | head -n1 | grep -q " 200"'
check "index.html is the web app" 'grep -q "id=\"root\"" "$TMP/index.html"'
for h in "content-security-policy: default-src 'self'" "x-content-type-options: nosniff" \
         "strict-transport-security:" "x-frame-options: DENY" "referrer-policy: no-referrer"; do
  check "header $h" 'echo "$H" | tr -d "\r" | grep -qi "^$h"'
done
check "no nginx version in Server header" '! echo "$H" | grep -qi "^server: nginx/"'
if [ -n "$HTTP_BASE" ]; then
  code="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$HTTP_BASE/")"
  check "http redirects to https (308)" '[ "$code" = 308 ]'
fi
FONT="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/fonts/Vazirmatn-Regular.woff2")"
check "bundled Persian font is served" '[ "$FONT" = 200 ]'
SPA="$("${CURL[@]}" -o /dev/null -w '%{http_code}' "$BASE/workspaces")"
check "SPA route falls back to index.html" '[ "$SPA" = 200 ]'

echo "== API envelope and limits"
R="$("${CURL[@]}" -D "$TMP/h" -w '\n%{http_code}' "$BASE/api/v1/auth/me")"
check "unauthenticated /auth/me is 401" '[ "$(echo "$R" | tail -n1)" = 401 ]'
check "error envelope has code unauthenticated" 'echo "$R" | grep -q "\"code\":\"unauthenticated\""'
check "X-Request-ID present" 'grep -qi "^x-request-id: " "$TMP/h"'
R="$("${CURL[@]}" -w '\n%{http_code}' -X POST -H 'Content-Type: multipart/form-data; boundary=x' \
      -H 'Content-Length: 300000000' --data-binary 'x' "$BASE/api/v1/workspaces/00000000-0000-0000-0000-000000000000/files")"
check "oversize upload is 413 with JSON file_too_large (from nginx)" \
  '[ "$(echo "$R" | tail -n1)" = 413 ] && echo "$R" | grep -q "\"code\":\"file_too_large\""'

echo "== slice: sign in -> upload CSV -> grid"
R="$("${CURL[@]}" -c "$JAR" -H 'Content-Type: application/json' \
      -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASS\"}" "$BASE/api/v1/auth/login")"
CSRF="$(echo "$R" | field csrf_token)"
check "login returns a CSRF token" '[ -n "$CSRF" ]'
[ -z "$CSRF" ] && { echo "cannot continue without a session"; exit 1; }
check "session cookie is HttpOnly + Secure" 'grep -q "HttpOnly" "$JAR" && awk "\$4==\"TRUE\"" "$JAR" | grep -q .'
auth=(-b "$JAR" -H "X-CSRF-Token: $CSRF")

WS="$("${CURL[@]}" "${auth[@]}" -H 'Content-Type: application/json' -d '{"name":"smoke test"}' "$BASE/api/v1/workspaces" | field id)"
check "workspace created" '[ -n "$WS" ]'
printf 'نام,تعداد,شهر\nعلی,3,تهران\nرضا,4.5,شیراز\n' > "$TMP/data.csv"
UP="$("${CURL[@]}" "${auth[@]}" -F "file=@$TMP/data.csv;filename=smoke.csv" "$BASE/api/v1/workspaces/$WS/files")"
JOB="$(echo "$UP" | field job_id)"
check "upload accepted and import job queued" '[ -n "$JOB" ]'
STATUS=""
for _ in $(seq 1 60); do
  J="$("${CURL[@]}" "${auth[@]}" "$BASE/api/v1/jobs/$JOB")"
  STATUS="$(echo "$J" | field status)"
  [ "$STATUS" = succeeded ] || [ "$STATUS" = failed ] && break
  sleep 0.5
done
check "import job succeeded" '[ "$STATUS" = succeeded ]'
WB="$(echo "$J" | field result_ref)"
META="$("${CURL[@]}" "${auth[@]}" "$BASE/api/v1/workbooks/$WB")"
SHEET="$(echo "$META" | sed -n 's/.*"sheets":\[{"id":"\([^"]*\)".*/\1/p')"
check "workbook has a sheet" '[ -n "$SHEET" ]'
CELLS="$("${CURL[@]}" "${auth[@]}" "$BASE/api/v1/workbooks/$WB/sheets/$SHEET/cells?r0=0&c0=0&rows=10&cols=10")"
check "grid window contains the Persian text" 'echo "$CELLS" | grep -q "شیراز"'
check "grid window contains a typed number" 'echo "$CELLS" | grep -q "\"n\":4.5"'
check "compatibility report is present" '"${CURL[@]}" "${auth[@]}" "$BASE/api/v1/workbooks/$WB/compatibility" | grep -q "\"source\":\"import\""'

echo "== cleanup and sign out"
D="$("${CURL[@]}" "${auth[@]}" -o /dev/null -w '%{http_code}' -X DELETE "$BASE/api/v1/workspaces/$WS?confirm=true")"
check "workspace deleted (204)" '[ "$D" = 204 ]'
O="$("${CURL[@]}" "${auth[@]}" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/v1/auth/logout")"
check "logout (204)" '[ "$O" = 204 ]'
M="$("${CURL[@]}" -b "$JAR" -o /dev/null -w '%{http_code}' "$BASE/api/v1/auth/me")"
check "session is gone after logout" '[ "$M" = 401 ]'

echo
if [ "$fails" -eq 0 ]; then echo "SMOKE OK"; else echo "SMOKE FAILED: $fails check(s)"; exit 1; fi
