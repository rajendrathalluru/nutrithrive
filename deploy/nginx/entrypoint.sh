#!/bin/sh
set -eu

cat > /usr/share/nginx/html/env-config.js <<EOF
window.__APP_CONFIG__ = {
  REACT_APP_BACKEND_URL: "${REACT_APP_BACKEND_URL:-http://localhost:8000}"
};
EOF

exec nginx -g 'daemon off;'
