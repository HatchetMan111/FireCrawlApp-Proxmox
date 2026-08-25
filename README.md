# 📈 FireCrawlApp

Preis-Monitoring-Dashboard für Produktseiten, die normale Scraper blockieren
(JS-Rendering, Bot-Schutz). Läuft als **LXC-Container auf Proxmox VE**, installierbar mit
**einem Einzeiler** im Stil der [Proxmox VE Community Scripts](https://community-scripts.github.io/ProxmoxVE).

- **Extraktion:** Firecrawl-API (Browser-Rendering + strukturiertes Extraction-Schema),
  Tavily-Extract-API als Fallback mit deutschem Preis-Parser (`701,00 €`, `€ 1.299,99`, `89,- €`, UVP-„Statt“-Fall)
- **Stack:** Python/FastAPI + SQLite + Chart.js (keine externen Dienste nötig; API-Keys optional → Demo-Modus)
- **Reboot-sicher:** systemd-Unit (`Restart=always`, `After=network-online.target`), CT mit `onboot: 1`

## 🚀 Installation (Einzeiler auf dem Proxmox-Host)

```bash
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/FireCrawlApp-Proxmox/main/install/firecrawlapp.sh)"
```

Das Script:

1. erstellt einen **unprivilegierten Debian-12-LXC** (2 vCPU / 1024 MB RAM / 6 GB Disk, DHCP, `onboot=1`)
2. lädt den App-Code aus diesem Repo und installiert Python-venv + Dependencies
3. richtet den systemd-Service `firecrawlapp` ein (bindet an `0.0.0.0:8000`)
4. **verifiziert sich selbst**: `systemctl is-active` + HTTP-Check auf `localhost:8000`
5. gibt die finale URL mit Container-IP aus

Erwartete Ausgabe (Auszug):

```
✅ Container 150 erstellt (onboot=1, unprivilegiert)
✅ Container-IP: 192.168.1.50
⏳ Installiere FireCrawlApp im Container (Python, venv, systemd) – einige Minuten
✅ Installation im Container abgeschlossen
✅ Service: active | WebUI: HTTP 200
✅ FireCrawlApp erfolgreich installiert (Modus: install)!
  WebUI : http://192.168.1.50:8000
```

### Optionale Umgebungsvariablen

| Variable | Default | Bedeutung |
|---|---|---|
| `CTID` | nächste freie | Container-ID |
| `PORT` | `8000` | WebUI-Port |
| `CORE_COUNT` / `RAM_SIZE` / `DISK_SIZE` | `2` / `1024` / `6` | Ressourcen |
| `STORAGE` / `TEMPLATE_STORAGE` | `local-lvm` / `local` | Storages |
| `BRG` / `NET_IP` / `NET_GW` | `vmbr0` / `dhcp` | Netzwerk |
| `FORCE=1` | – | Bestätigungsfrage überspringen |

Beispiel: `CTID=150 PORT=8080 bash -c "$(wget -qLO - ...)"`

### Idempotenz

Der Einzeiler kann beliebig oft erneut ausgeführt werden:

- CT existiert bereits **und gehört zu FireCrawlApp** → **Update-Modus**
  (Code neu aus dem Repo, `pip install`, `.env` und SQLite-Datenbank bleiben erhalten)
- CT existiert und gehört zu **einem anderen Projekt** → Installer weicht automatisch
  auf die nächste freie CT-ID aus

## 🔧 Konfiguration

**API-Keys direkt im Dashboard eingeben:** oben rechts **⚙️ Einstellungen** → Keys eintragen →
*Speichern & prüfen*. Die Keys werden nur lokal im Container (SQLite) gespeichert, der
Demo-Modus schaltet sich automatisch ab (sofern auf „auto“), und alle Produkte werden
sofort mit den echten APIs geprüft.

### Prüfintervall pro Produkt

Jedes Produkt hat ein eigenes **Prüfintervall** (Dropdown direkt in der Tabelle oder im
Detail-Dialog): 1 Std / 3 Std / 6 Std / 12 Std / 1 Tag / 2 Tage / 7 Tage. Der Scheduler läuft
alle `CHECK_INTERVAL_MINUTES` (Standard 15 Min, nur DB-Scan, keine API-Kosten) und prüft
ausschließlich Produkte, deren Intervall abgelaufen ist — so werden keine unnötigen
API-Calls verschwendet. „⟳ Jetzt prüfen“ prüft unabhängig vom Intervall sofort.

Alterniv via Datei `/opt/firecrawlapp/.env`:

```ini
FIRECRAWL_API_KEY=fc-...        # https://firecrawl.dev
TAVILY_API_KEY=tvly-...         # https://tavily.com (optional, Fallback)
CHECK_INTERVAL_MINUTES=15       # Scheduler-Loop (prüft nur fällige Produkte)
DEMO_MODE=auto                  # auto|on|off (auto = Demo ohne Keys)
```

Danach: `systemctl restart firecrawlapp`. Im Demo-Modus (`auto` ohne Keys) werden simulierte
Preise erzeugt; beenden entweder per Key-Eintrag oder über den Banner (**Demo beenden**).
Demo-Produkte lassen sich im Einstellungs-Dialog per Klick entfernen. Existiert eine URL
schon als Demo-Produkt, wird sie beim Hinzufügen automatisch übernommen und echt geprüft.

Hinweis: In der DB gespeicherte Keys haben Vorrang vor der `.env`; Feld leer speichern = löschen.

## 🔄 Update & Deinstallation

```bash
# Update Option 1: Einzeiler erneut ausführen (erkennt bestehende Installation)
# Update Option 2 (im Container):
pct exec <CTID> -- update-firecrawlapp

# Deinstallation:
pct stop <CTID> && pct destroy <CTID>
```

## 🐞 Debugging

Bei Fehlern gibt das Install-Script die **komplette Fehlerkette** aus
(fehlgeschlagener Schritt, Exit-Code, Log-Auszüge). Vollständiger Trace:

```bash
DEBUG=1 bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/FireCrawlApp-Proxmox/main/install/firecrawlapp.sh)"
# Trace landet in /tmp/firecrawlapp-install.log.trace bzw. .log
```

Logs im Container:

```bash
pct exec <CTID> -- journalctl -u firecrawlapp -n 100 --no-pager   # Service-Log
pct exec <CTID> -- cat /tmp/firecrawlapp-install.log              # Installer-Log
```

## ✅ Testdurchlauf (Protokoll)

Auf einem Proxmox-Host mit mindestens freier CT-ID:

```bash
# 1) Installation
bash -c "$(wget -qLO - https://raw.githubusercontent.com/HatchetMan111/FireCrawlApp-Proxmox/main/install/firecrawlapp.sh)"
# → endet mit "WebUI : http://<IP>:8000", Verifikation "Service: active | WebUI: HTTP 200"

# 2) Reboot des LXC
pct reboot <CTID>

# 3) Web UI nach Reboot wieder erreichbar?
sleep 20 && curl -s http://<IP>:8000/api/status    # → {"firecrawl":...,"demo":true,...}
pct exec <CTID> -- systemctl is-active firecrawlapp  # → active
```

Zusätzlich lokal verifiziert (CI-fähig, ohne Proxmox): `bash -n`, `shellcheck` (0 Warnungen),
kompletter Host-Flow gegen gemockte `pct/pveam/pvesh`-Binaries in allen drei Zweigen
(Neuinstallation / Update / ID-Ausweich), Container-Installer halb-reAL mit echtem
venv+pip inklusive Idempotenz-Nachweis (`.env` bleibt bei Re-Run erhalten).

### Notizen & Feedback

- **📝 Notiz pro Produkt** (Detail-Dialog): z.B. „Preis gilt pro Palette, nicht pro m²“ —
  erscheint unter dem Produktnamen in der Tabelle.
- **Ereignis-Log mit Ergebnis-Feedback:** jeder Check erzeugt einen Eintrag —
  🟢/🔴 bei Preisänderung, ✅ bei unverändertem/erstem Preis. So ist immer sichtbar,
  ob eine Prüfung erfolgreich war.
- **Fehlgeschlagene Checks** (z.B. „no price found“) enthalten einen Tipp, einen zweiten
  Provider (Firecrawl/Tavily) als Fallback zu hinterlegen; die Extraktion versteht deutsche
  Preisformate und ignoriert UVP-/„Statt“-Preise.
- **URL schon vorhanden?** Kein Blocker mehr: Hat das Produkt noch nie einen Preis geliefert,
  wird es beim erneuten Hinzufügen automatisch zurückgesetzt und frisch geprüft. Bei einem
  aktiven Produkt fragt das Dashboard „Historie zurücksetzen & neu prüfen?“ an.

## 🖥️ Lokale Entwicklung (ohne Proxmox)

```bash
./run.sh        # erstellt .venv, startet auf http://0.0.0.0:8000
```

## API (kurz)

| Endpoint | Beschreibung |
|---|---|
| `GET /api/products` | Produkte inkl. Historie/Änderung |
| `POST /api/products` | `{url, name?}` – legt an & prüft sofort |
| `POST /api/products/{id}/check` · `POST /api/check-all` | Prüfung starten |
| `GET /api/products/{id}/history?days=30` | Preis-Historie |
| `GET /api/events` · `GET /api/status` | Alerts / Provider-Status |

## ⚖️ Nutzungsbedingungen

Automatisierte Preisabfragen sind Scraping – Rate Limits respektieren und die
Nutzungsbedingungen der jeweiligen Shops beachten.
