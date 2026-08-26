#!/bin/sh
set -eu
cat > /usr/share/nginx/html/runtime-config.js <<EOF
window.__APP_VERSION__="${APP_VERSION:-0.0.0}";
window.__FRONTEND_IMAGE__="${FRONTEND_IMAGE:-}";
window.__BACKEND_IMAGE__="${BACKEND_IMAGE:-}";
EOF
exec nginx -g 'daemon off;'
