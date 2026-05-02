#!/usr/bin/env bash
# Idempotent installer for the KeeperKit demo server on Ubuntu/Debian.
#
# Usage:
#   curl -sSfL https://raw.githubusercontent.com/danilaverbena/keeperkit/main/deploy/install.sh \
#     | bash
#
# Or, locally, after cloning the repo:
#   sudo bash deploy/install.sh
#
# Environment variables read at install time:
#   KEEPERHUB_API_KEY  - optional; the demo runs in mock mode without it.
#   OPENAI_API_KEY     - optional; enables the LangChain ReAct agent.
#   KEEPERKIT_DOMAIN   - optional; configures nginx server_name.

set -euo pipefail

REPO_URL="${KEEPERKIT_REPO:-https://github.com/danilaverbena/keeperkit}"
TARGET="${KEEPERKIT_DIR:-/opt/keeperkit}"
PORT="${KEEPERKIT_PORT:-8000}"
DOMAIN="${KEEPERKIT_DOMAIN:-_}"

log() { printf '\033[1;32m[keeperkit-install]\033[0m %s\n' "$*"; }

if [ "$(id -u)" -ne 0 ]; then
    echo "Run me as root (sudo bash deploy/install.sh)." >&2
    exit 1
fi

log "Installing system packages…"
apt-get update -y
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    git curl ca-certificates python3 python3-venv python3-pip nginx

log "Cloning / updating repo at ${TARGET}…"
if [ -d "${TARGET}/.git" ]; then
    git -C "${TARGET}" fetch --quiet origin
    git -C "${TARGET}" reset --quiet --hard origin/main
else
    rm -rf "${TARGET}"
    git clone --quiet "${REPO_URL}" "${TARGET}"
fi

log "Creating Python virtualenv…"
python3 -m venv "${TARGET}/.venv"
"${TARGET}/.venv/bin/pip" install --quiet --upgrade pip
"${TARGET}/.venv/bin/pip" install --quiet -e "${TARGET}[server,langchain]"

log "Writing environment file…"
ENV_FILE="${TARGET}/.env"
if [ ! -f "${ENV_FILE}" ]; then
    cp "${TARGET}/.env.example" "${ENV_FILE}"
fi
# Inject runtime values (only if not already set in the file).
grep -q "^KEEPERKIT_PORT=" "${ENV_FILE}" \
    && sed -i "s|^KEEPERKIT_PORT=.*|KEEPERKIT_PORT=${PORT}|" "${ENV_FILE}" \
    || echo "KEEPERKIT_PORT=${PORT}" >> "${ENV_FILE}"
if [ -n "${KEEPERHUB_API_KEY:-}" ]; then
    sed -i "s|^KEEPERHUB_API_KEY=.*|KEEPERHUB_API_KEY=${KEEPERHUB_API_KEY}|" "${ENV_FILE}" \
        || echo "KEEPERHUB_API_KEY=${KEEPERHUB_API_KEY}" >> "${ENV_FILE}"
fi
if [ -n "${OPENAI_API_KEY:-}" ]; then
    sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${OPENAI_API_KEY}|" "${ENV_FILE}" \
        || echo "OPENAI_API_KEY=${OPENAI_API_KEY}" >> "${ENV_FILE}"
fi

log "Installing systemd unit…"
install -m 0644 "${TARGET}/deploy/keeperkit.service" /etc/systemd/system/keeperkit.service
systemctl daemon-reload
systemctl enable keeperkit
systemctl restart keeperkit

log "Configuring nginx…"
NGINX_FILE=/etc/nginx/sites-available/keeperkit
sed "s|server_name _;|server_name ${DOMAIN};|" \
    "${TARGET}/deploy/keeperkit.nginx.conf" > "${NGINX_FILE}"
ln -sf "${NGINX_FILE}" /etc/nginx/sites-enabled/keeperkit
# Disable the default nginx welcome page if it's still around.
[ -L /etc/nginx/sites-enabled/default ] && rm -f /etc/nginx/sites-enabled/default || true
nginx -t
systemctl reload nginx

log "All done. Try: curl -s http://localhost/api/health"
