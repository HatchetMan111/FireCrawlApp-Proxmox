#!/usr/bin/env bash
# ============================================================================
# FireCrawlApp – Proxmox VE Installer (Community-Scripts-Stil)
# ============================================================================
# Einzeiler:
#   bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/FireCrawlApp-Proxmox/main/install/firecrawlapp.sh)"
#
# Erstellt einen LXC-Container und installiert FireCrawlApp (Preis-Monitoring
# Dashboard via Firecrawl/Tavily-API) inkl. systemd-Service.
#
# Idempotent: Nochmalige Ausführung aktualisiert eine bestehende Installation.
# Debug:      DEBUG=1 bash -c "$(wget -qLO - <url>)"   (bash -x Trace)
#
# Umgebungsvariablen (optional):
#   CTID=150          Container-ID (Default: nächste freie)
#   PORT=8000         WebUI-Port
#   STORAGE=local-lvm Root-Disk-Storage
#   RAM_SIZE=1024, CORE_COUNT=2, DISK_SIZE=6
#   FORCE=1           Bestätigungsfrage überspringen
# ============================================================================

set -Eeuo pipefail

APP="FireCrawlApp"
SLUG="firecrawlapp"
REPO_RAW="${REPO_RAW:-https://raw.githubusercontent.com/HatchetMan111/FireCrawlApp-Proxmox/main}"
PORT="${PORT:-8000}"
CORE_COUNT="${CORE_COUNT:-2}"
RAM_SIZE="${RAM_SIZE:-1024}"
DISK_SIZE="${DISK_SIZE:-6}"
STORAGE="${STORAGE:-local-lvm}"
TEMPLATE_STORAGE="${TEMPLATE_STORAGE:-local}"
BRG="${BRG:-vmbr0}"
NET_IP="${NET_IP:-dhcp}"
NET_GW="${NET_GW:-}"
HN="${HN:-firecrawlapp}"
var_os="${var_os:-debian}"
var_version="${var_version:-12}"
var_unprivileged="${var_unprivileged:-1}"
CT_MARK="firecrawlapp-managed"
LOG_FILE="/tmp/${SLUG}-install.log"

if [[ "${DEBUG:-0}" == "1" ]]; then
  set -x
  exec 2> >(tee -a "${LOG_FILE}.trace" >&2)
fi

GN=$'\033[1;92m' CL=$'\033[0m' RD=$'\033[01;31m' YW=$'\033[33m' BL=$'\033[36m' DGN=$'\033[32m'

msg_info() { echo -e "${YW}⏳ $1${CL}"; }
msg_ok() { echo -e "${GN}✅ $1${CL}"; }
msg_error() { echo -e "${RD}❌ $1${CL}"; }

on_error() {
  local exit_code=$?
  local line_no=${1:-"?"}
  echo ""
  msg_error "Installation fehlgeschlagen (Exit-Code ${exit_code}, Zeile ${line_no})."
  echo -e "${YW}── Fehlerkette ─────────────────────────────────────────────${CL}"
  echo -e "  Fehlgeschlagener Schritt : Zeile ${line_no} in ${0}"
  echo -e "  Exit-Code                : ${exit_code}"
  if [[ -f "${LOG_FILE}" ]]; then
    echo -e "  Letzte Log-Auszüge (${LOG_FILE}):"
    tail -n 25 "${LOG_FILE}" | sed 's/^/    | /'
  fi
  echo -e "${YW}── Debugging ───────────────────────────────────────────────${CL}"
  echo -e "  Vollständiger Trace:  DEBUG=1 bash -c \"\$(wget -qLO - ${REPO_RAW}/install/${SLUG}.sh)\""
  echo -e "  Trace-Datei          : ${LOG_FILE}.trace"
  echo -e "  Im Container:         pct enter <CTID> → journalctl -u ${SLUG} -n 100 --no-pager"
  exit "${exit_code}"
}

trap 'on_error $LINENO' ERR

header_info() {
  clear 2>/dev/null || true
  cat <<'EOF'
  ______ __  __  ____  ____  __  ___
 / ____// / / / / __ \/ __ \/  |/  /
/ /_   / /_/ / / /_/ / / / / /|_/ /
/ __/  / __  / / _, _/ / / / /  / /
/_/    /_/ /_//_/ |_/_/ /_/_/  /_/
  Preis-Monitoring Dashboard (Firecrawl / Tavily)
EOF
  echo -e "\n"
}

spinner() {
  local pid=$1
  local spin='-\|/' i=0
  while kill -0 "$pid" 2>/dev/null; do
    printf "\r${YW} %c${CL}" "${spin:i++%4:1}"
    sleep 0.3
  done
  printf "\r"
}

die() { msg_error "$1" >&2; exit 1; }

fetch_remote() {
  local url=$1
  local content
  if ! content=$(curl -fsSL --retry 3 --max-time 60 "$url" 2>"${LOG_FILE}.curl"); then
    msg_error "Download fehlgeschlagen: ${url}"
    [[ -s "${LOG_FILE}.curl" ]] && sed 's/^/    curl: /' "${LOG_FILE}.curl" >&2
    exit 1
  fi
  echo "$content"
}

header_info
echo -e "${DGN}FireCrawlApp – Proxmox LXC Installer${CL}"
echo -e "${DGN}Repo: ${REPO_RAW}${CL}"
echo ""

[[ $EUID -eq 0 || "${ALLOW_NONROOT:-0}" == "1" ]] || die "Bitte als root auf dem Proxmox-VE-Host ausführen (CI: ALLOW_NONROOT=1)."
command -v pct >/dev/null 2>&1 || die "pct nicht gefunden – dieses Script gehört auf einen Proxmox-VE-Host."
command -v pveam >/dev/null 2>&1 || die "pveam nicht gefunden – kein Proxmox-VE-Host?"

NEXTID=$(pvesh get /cluster/nextid 2>/dev/null || echo 100)
CTID="${CTID:-$NEXTID}"
MODE="install"

if pct status "$CTID" &>/dev/null; then
  if pct config "$CTID" 2>/dev/null | grep -q "${CT_MARK}"; then
    MODE="update"
    msg_info "CT ${CTID} ist eine bestehende ${APP}-Installation → Update-Modus"
    pct status "$CTID" | grep -q "status: stopped" && { msg_info "Starte gestoppten Container"; pct start "$CTID"; }
  else
    OLD_CTID=$CTID
    CTID=$(pvesh get /cluster/nextid)
    while pct status "$CTID" &>/dev/null; do
      CTID=$((CTID + 1))
    done
    msg_error "CT ${OLD_CTID} existiert bereits und gehört nicht zu ${APP}."
    msg_ok "Verwende stattdessen die nächste freie CT-ID: ${CTID}"
  fi
fi

if [[ "$MODE" == "install" ]]; then
  echo -e "${DGN}Einstellungen:${CL}"
  echo -e "${DGN}  CT-ID     : ${CTID}${CL}"
  echo -e "${DGN}  Hostname  : ${HN}${CL}"
  echo -e "${DGN}  Ressourcen: ${CORE_COUNT} vCPU / ${RAM_SIZE} MB RAM / ${DISK_SIZE} GB Disk (${STORAGE})${CL}"
  echo -e "${DGN}  Netzwerk  : ${BRG} (${NET_IP})${CL}"
  echo -e "${DGN}  WebUI     : Port ${PORT}${CL}"
  if [[ "${FORCE:-0}" != "1" && -t 0 ]]; then
    read -rp "Installation starten? [j/N]: " CONFIRM
    [[ "${CONFIRM,,}" == "j" || "${CONFIRM,,}" == "y" ]] || die "Abgebrochen."
  fi

  msg_info "Aktualisiere Template-Liste"
  pveam update >/dev/null 2>&1 || true
  msg_ok "Template-Liste aktuell"

  TEMPLATE=$(pveam available --section system 2>/dev/null | awk '/debian-12-standard/ {print $2; exit}')
  [[ -n "$TEMPLATE" ]] || die "Kein Debian-12-Template gefunden. Ist das CFS-Template-Repo eingebunden?"
  if ! pveam list "$TEMPLATE_STORAGE" 2>/dev/null | grep -q "$TEMPLATE"; then
    msg_info "Lade Debian-12-Template herunter (${TEMPLATE})"
    pveam download "$TEMPLATE_STORAGE" "$TEMPLATE" >/dev/null &
    spinner $!
    msg_ok "Template heruntergeladen"
  else
    msg_ok "Template vorhanden: ${TEMPLATE}"
  fi
  TEMPLATE_PATH="${TEMPLATE_STORAGE}:vztmpl/${TEMPLATE}"

  msg_info "Erstelle LXC-Container ${CTID} (unprivilegiert)"
  pct create "$CTID" "$TEMPLATE_PATH" \
    --hostname "$HN" \
    --cores "$CORE_COUNT" \
    --memory "$RAM_SIZE" \
    --swap 512 \
    --rootfs "${STORAGE}:${DISK_SIZE}" \
    --net0 "name=eth0,bridge=${BRG},ip=${NET_IP},firewall=0$( [[ -n "$NET_GW" ]] && printf ',gw=%s' "$NET_GW" ),type=veth" \
    --ostype debian \
    --unprivileged "$var_unprivileged" \
    --onboot 1 \
    --start 0 \
    --tags "${SLUG};community-style" \
    --description "${CT_MARK}: ${APP} – Preis-Monitoring via Firecrawl/Tavily. WebUI-Port ${PORT}. Config: /opt/${SLUG}/.env" \
    >/dev/null 2>&1 &
  spinner $!
  msg_ok "Container ${CTID} erstellt (onboot=1, unprivilegiert)"
fi

msg_info "Starte Container ${CTID}"
pct start "$CTID" >/dev/null 2>&1 &
spinner $!
msg_ok "Container gestartet"

msg_info "Warte auf Netzwerk im Container"
IP=""
for _ in $(seq 1 45); do
  IP=$(pct exec "$CTID" -- hostname -I 2>/dev/null | awk '{print $1}') || true
  [[ -n "$IP" ]] && break
  sleep 2
done
[[ -n "$IP" ]] || die "Container hat nach 90s keine IP erhalten (DHCP?)."
msg_ok "Container-IP: ${IP}"

msg_info "Lade Container-Installer aus dem Repo"
INSTALLER_CONTENT=$(fetch_remote "${REPO_RAW}/install/${SLUG}-install.sh")
[[ ${#INSTALLER_CONTENT} -gt 500 ]] || die "Installer ungültig (zu kurz) – Repo-URL prüfen."
msg_ok "Installer geladen"

if [[ "${REPO_RAW}" == *raw.githubusercontent.com* ]]; then
  GITHUB_SLUG=$(echo "${REPO_RAW#https://raw.githubusercontent.com/}" | cut -d'/' -f1-2)
  APP_SOURCE_URL="${APP_SOURCE_URL:-https://codeload.github.com/${GITHUB_SLUG}/tar.gz/refs/heads/main}"
else
  APP_SOURCE_URL="${APP_SOURCE_URL:-}"
fi

msg_info "Installiere ${APP} im Container (Python, venv, systemd) – einige Minuten"
printf '%s\n' "$INSTALLER_CONTENT" | pct exec "$CTID" -- bash -c 'cat > /tmp/'"${SLUG}"'-install.sh'
pct exec "$CTID" -- bash -c "APP_SOURCE_URL='${APP_SOURCE_URL:-}' PORT='${PORT}' REPO_RAW='${REPO_RAW}' bash /tmp/${SLUG}-install.sh" 2>&1 | tee -a "${LOG_FILE}"
msg_ok "Installation im Container abgeschlossen"

msg_info "Verifikation (Service + WebUI)"
SERVICE_OK=$(pct exec "$CTID" -- systemctl is-active "${SLUG}" 2>/dev/null || true)
[[ "$SERVICE_OK" == "active" ]] || die "Service '${SLUG}' ist nicht active (Status: ${SERVICE_OK:-unbekannt}). Siehe: pct exec ${CTID} -- journalctl -u ${SLUG} -n 50 --no-pager"

HTTP_OK=0
for _ in $(seq 1 15); do
  if pct exec "$CTID" -- curl -fsS "http://localhost:${PORT}/api/status" >/dev/null 2>&1; then
    HTTP_OK=1
    break
  fi
  sleep 2
done
[[ "$HTTP_OK" == "1" ]] || die "WebUI antwortet nicht auf localhost:${PORT}. Log: pct exec ${CTID} -- journalctl -u ${SLUG} -n 100 --no-pager"
msg_ok "Service: active | WebUI: HTTP 200"

HOST_OK=0
for _ in $(seq 1 5); do
  if curl -fsS --max-time 5 "http://${IP}:${PORT}/api/status" >/dev/null 2>&1; then
    HOST_OK=1
    break
  fi
  sleep 2
done
if [[ "$HOST_OK" == "1" ]]; then
  msg_ok "WebUI vom Proxmox-Host erreichbar"
else
  msg_error "WebUI vom Host aus nicht erreichbar (PVE-Firewall/Datenzentrum-Regeln prüfen) – im Container läuft sie."
fi

echo ""
msg_ok "${APP} erfolgreich installiert (Modus: ${MODE})!"
echo -e ""
echo -e "${GN}──────────────────────────────────────────────────────────${CL}"
echo -e "${GN}  WebUI : ${BL}http://${IP}:${PORT}${CL}"
echo -e "${GN}  CT-ID : ${BL}${CTID}${CL}"
echo -e "${GN}──────────────────────────────────────────────────────────${CL}"
echo -e ""
echo -e "${YW}API-Keys eintragen (optional, sonst Demo-Modus):${CL}"
echo -e "  pct exec ${CTID} -- nano /opt/${SLUG}/.env"
echo -e "  pct exec ${CTID} -- systemctl restart ${SLUG}"
echo -e "${YW}Updates:${CL} diesen Einzeiler erneut ausführen (idempotent) oder:"
echo -e "  pct exec ${CTID} -- update-${SLUG}"
echo -e "${YW}Logs:${CL}    pct exec ${CTID} -- journalctl -u ${SLUG} -f"
echo -e "${YW}Konsole:${CL} pct enter ${CTID}"
