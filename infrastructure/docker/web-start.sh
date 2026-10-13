#!/bin/sh
set -eu
# Keep the published address canonical and IPv4 loopback-only.
if ! printf '%s\n' "${LOCAL_WEB_HOST:-}" | awk -F. '
  NF != 4 || $1 != "127" { exit 1 }
  { for (i=1; i<=4; i++) if ($i !~ /^[0-9]+$/ || $i > 255 ||
      (length($i) > 1 && substr($i,1,1) == "0")) exit 1 }
'; then
  echo "LOCAL_WEB_HOST must be a canonical IPv4 loopback address." >&2; exit 1
fi
case "${LOCAL_WEB_PORT:-}" in
  ''|*[!0-9]*|0*) echo "LOCAL_WEB_PORT must be a canonical TCP port." >&2; exit 1 ;;
esac
if [ "$LOCAL_WEB_PORT" -gt 65535 ]; then
  echo "LOCAL_WEB_PORT must be between 1 and 65535." >&2; exit 1
fi
if [ "${#LOCAL_PROXY_SECRET}" -ne 64 ]; then
  echo "Generate a 32-byte lowercase hex LOCAL_PROXY_SECRET." >&2; exit 1
fi
case "$LOCAL_PROXY_SECRET" in
  *[!0-9a-f]*) echo "LOCAL_PROXY_SECRET must be lowercase hex." >&2; exit 1 ;;
esac
umask 077
authority="${LOCAL_WEB_HOST}:${LOCAL_WEB_PORT}"
if [ "$LOCAL_WEB_PORT" -eq 80 ]; then
  authority="$LOCAL_WEB_HOST"
fi
cat > /etc/nginx/conf.d/local.conf <<EOF
server {
    listen 8080 default_server;
    server_name _;
    if (\$http_host != "${authority}") { return 421; }
    root /usr/share/nginx/html;
    access_log off;
    server_tokens off;
    location / { try_files \$uri \$uri/ =404; }
    location = /api/health {
        proxy_pass http://api:8000/health;
        proxy_set_header Host \$http_host;
        proxy_set_header Origin \$http_origin;
        proxy_set_header X-Local-Proxy-Secret "${LOCAL_PROXY_SECRET}";
    }
    location /api/ {
        proxy_pass http://api:8000;
        proxy_set_header Host \$http_host;
        proxy_set_header Origin \$http_origin;
        proxy_set_header X-Local-Proxy-Secret "${LOCAL_PROXY_SECRET}";
    }
}
EOF
