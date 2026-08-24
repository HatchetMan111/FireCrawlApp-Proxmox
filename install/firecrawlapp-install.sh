#!/usr/bin/env bash
# ============================================================================
# FireCrawlApp – Container-Installer (läuft IM LXC, Debian 11/12)
# ============================================================================
# Wird von install/firecrawlapp.sh (Host) oder dem Community-build.func
# (FUNCTIONS_FILE_PATH gesetzt) aufgerufen. Idempotent: bestehende .env und
# SQLite-Datenbank bleiben bei Updates erhalten.
#
# Umgebungsvariablen:
#   PORT=8000          WebUI-Port
#   APP_SOURCE_URL     Tarball-URL des App-Codes (GitHub codeload tar.gz)
#   REPO_RAW           Raw-Basis-URL des Repos (Fallback für Unit-Datei)
# ============================================================================

set -Eeuo pipefail

APP="FireCrawlApp"
SLUG="firecrawlapp"
APP_DIR="${APP_DIR:-/opt/${SLUG}}"
SERVICE="${SLUG}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
BIN_DIR="${BIN_DIR:-/usr/local/bin}"
PORT="${PORT:-8000}"
APP_SOURCE_URL="${APP_SOURCE_URL:-}"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/HatchetMan111/FireCrawlApp-Proxmox/main}"
LOG_FILE="/tmp/${SLUG}-install.log"

exec > >(tee -a "${LOG_FILE}") 2>&1

if [[ -n "${FUNCTIONS_FILE_PATH:-}" ]]; then
  source /dev/stdin <<<"$FUNCTIONS_FILE_PATH"
  color
  verb_ip6
  catch_errors
  setting_up_container
  network_check
  update_os
else
  GN=$'\033[1;92m' YW=$'\033[33m' RD=$'\033[01;31m' CL=$'\033[0m'
  msg_info() { echo -e "${YW}⏳ $1${CL}"; }
  msg_ok() { echo -e "${GN}✅ $1${CL}"; }
  msg_error() { echo -e "${RD}❌ $1${CL}"; }
  STD=""
  export DEBIAN_FRONTEND=noninteractive
fi

on_error() {
  local exit_code=$?
  local line_no=${1:-"?"}
  echo ""
  msg_error "Installer fehlgeschlagen (Exit-Code ${exit_code}, Zeile ${line_no})."
  echo -e "── Fehlerkette ──────────────────────────────"
  echo -e "  Schritt : Zeile ${line_no}"
  echo -e "  Log     : ${LOG_FILE} (vollständig: tail -n 100 ${LOG_FILE})"
  if command -v journalctl >/dev/null 2>&1 && systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}"; then
    echo -e "  Service-Log (letzte 30 Zeilen):"
    journalctl -u "${SERVICE}" -n 30 --no-pager | sed 's/^/    | /' || true
  fi
  exit "${exit_code}"
}

fail_hard() {
  msg_error "$1"
  if command -v journalctl >/dev/null 2>&1; then
    journalctl -u "${SERVICE}" -n 50 --no-pager | sed 's/^/    | /' || true
  fi
  echo -e "    | ---- Installer-Log ----"
  tail -n 40 "${LOG_FILE}" | sed 's/^/    | /'
  exit 1
}
trap 'on_error $LINENO' ERR

msg_info "Installing Dependencies"
$STD apt-get update -y
$STD apt-get install -y python3 python3-venv curl ca-certificates
msg_ok "Installed Dependencies"

msg_info "Setting up ${APP} in ${APP_DIR}"
mkdir -p "$APP_DIR"
curl -fsSL --retry 3 --max-time 120 "$APP_SOURCE_URL" | tar -xz --strip-components=1 -C "$APP_DIR"
[[ -f "${APP_DIR}/app/main.py" ]] || fail_hard "App-Code nicht gefunden (APP_SOURCE_URL=${APP_SOURCE_URL:-leer})."
msg_ok "App-Code nach ${APP_DIR} entpackt (bestehende .env/data bleiben erhalten)"

msg_info "Setup Python venv & Dependencies"
if [[ ! -d "${APP_DIR}/.venv" ]]; then
  python3 -m venv "${APP_DIR}/.venv"
fi
"${APP_DIR}/.venv/bin/pip" install --no-cache-dir -q --upgrade pip
"${APP_DIR}/.venv/bin/pip" install --no-cache-dir -q -r "${APP_DIR}/requirements.txt"
if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  echo "INFO: Neue .env angelegt – API-Keys optional eintragen."
else
  echo "INFO: Bestehende .env unverändert übernommen."
fi
msg_ok "Python venv & Dependencies"

msg_info "Creating systemd Service (${SERVICE}.service)"
mkdir -p "$UNIT_DIR"
if [[ -f "${APP_DIR}/install/${SLUG}.service" ]]; then
  sed "s/__PORT__/${PORT}/g" "${APP_DIR}/install/${SLUG}.service" > "${UNIT_DIR}/${SERVICE}.service"
else
  cat <<EOF > "${UNIT_DIR}/${SERVICE}.service"
[Unit]
Description=${APP} Price Tracking Dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
Environment=PORT=${PORT}
Environment=TZ=Europe/Berlin
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port \${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
fi
systemctl daemon-reload
systemctl enable -q --now "${SERVICE}"
msg_ok "Created Service (Restart=always, After=network-online.target)"

mkdir -p "$BIN_DIR"
cat <<UPDATE > "${BIN_DIR}/update-${SLUG}"
#!/usr/bin/env bash
set -euo pipefail
cd ${APP_DIR}
curl -fsSL --retry 3 '${APP_SOURCE_URL}' | tar -xz --strip-components=1 -C ${APP_DIR}
.venv/bin/pip install --no-cache-dir -q -r requirements.txt
systemctl restart ${SERVICE}
echo "${APP} aktualisiert & neu gestartet."
UPDATE
chmod +x "${BIN_DIR}/update-${SLUG}"

if command -v motd_ssh >/dev/null 2>&1; then motd_ssh; fi
if command -v customize >/dev/null 2>&1; then customize; fi

msg_info "Cleaning up"
$STD apt-get -y autoremove
$STD apt-get -y autoclean
rm -f "/tmp/${SLUG}-install.sh"
msg_ok "Cleaned"

msg_info "Verifikation: Service & WebUI"
SYSTEMD_OK=0
for _ in $(seq 1 15); do
  if systemctl is-active --quiet "$SERVICE"; then SYSTEMD_OK=1; break; fi
  sleep 2
done
[[ "$SYSTEMD_OK" == "1" ]] || fail_hard "Systemd-Service '${SERVICE}' ist nicht active."

HTTP_OK=0
for _ in $(seq 1 30); do
  if curl -fsS --max-time 5 "http://localhost:${PORT}/api/status" >/dev/null 2>&1; then
    HTTP_OK=1
    break
  fi
  sleep 1
done
[[ "$HTTP_OK" == "1" ]] || fail_hard "WebUI antwortet nicht auf localhost:${PORT}."
STATUS_JSON=$(curl -fsS "http://localhost:${PORT}/api/status")
msg_ok "Verifikation: Service active, WebUI HTTP 200 (${STATUS_JSON})"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo ""
echo -e "${GN}${APP} läuft!${CL}"
echo -e "  WebUI : http://${IP:-<container-ip>}:${PORT}"
echo -e "  Config: ${APP_DIR}/.env (FIRECRAWL_API_KEY / TAVILY_API_KEY)"
echo -e "  Danach: systemctl restart ${SERVICE}"
echo -e "  Logs  : journalctl -u ${SERVICE} -f"
echo -e "  Update: update-${SLUG}"
exit 0
