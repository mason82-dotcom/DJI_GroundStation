# DJI GroundStation

Serverstack für eine Bodenstation von DJI-Drohnen, aufgebaut auf
[**Lyrebird**](https://github.com/SDU-UAS-Center/lyrebird) des SDU UAS Center.

Die Lyrebird-App auf der DJI-Fernsteuerung (RC Pro, RC Plus oder Handy am RC-N3) lässt
die Drohne MAVLink 2 sprechen wie ein PX4-Fahrzeug. Zusätzlich bietet die App HTTP, TCP-Telemetrie
und WHIP-Video. Dieses Repository ist die **Bodenseite** dazu:
ein Docker-Compose-Stack mit Login und TLS. Er bündelt Lyrebird mit weiteren Werkzeugen des SDU UAS Center:

| Profil | Dienst | Herkunft | Zweck |
|---|---|---|---|
| *Kern* | `proxy` | Caddy | Ein Login und TLS für alle Web-Oberflächen; Portal-Startseite |
| *Kern* | `mediamtx` | MediaMTX | Video: WHIP-Ingest von der Drohne, WHEP (Browser), RTSP (QGroundControl) |
| *Kern* | `dashboard` | Lyrebird | Flotten-Dashboard: Video, Telemetrie, Einstellungen, ROS-Status |
| *Kern* | `mavlink-router` | mavlink-router | MAVLink an beliebig viele QGC-/MAVSDK-Clients (TCP 5760), `.tlog`-Flugaufzeichnung |
| `archive` | `media-sync` | eigen (Lyrebird-Client) | Telemetrie-Log pro Flug; Fotos und Videos nach der Landung von der SD-Karte ins Archiv |
| `ros` | `ros`, `ros-monitor` | Lyrebird | ROS-2-Bridge (`/<drohne>/fmu/in|out/…`), Lyrical, Jazzy oder Humble |
| `dvm` | `dvm-*` | [DVM](https://github.com/SDU-UAS-Center/DVM) | Drone Video Measure: Objekte in Drohnenvideos vermessen und verfolgen |
| `agro` | `qgis` | [sdu-agro-tools](https://github.com/SDU-UAS-Center/sdu-agro-tools) | QGIS-Desktop im Browser mit dem Plugin SDU Agro Tools |
| `agro` | `agro-api` | [crop-row-connector](https://github.com/SDU-UAS-Center/crop-row-connector), CDC, crop-row-detector | Batch-Jobs: Fotos → Orthomosaik → Segmentierung → Pflanzenreihen → Vitalität |
| `odm` | `nodeodm` | OpenDroneMap | Orthomosaike aus Drohnenfotos |
| `qgc` | `qgc` | [QGroundControl](https://github.com/mavlink/qgroundcontrol) v5.1.5 | QGC im Browser, fest mit dem MAVLink-Router verbunden (TCP 5760) |
| `tools` | `gs-tools` | Lyrebird | CLI: Discovery, Feldtest, Signing-Test, Flugbeispiele |
| `android` | `android-build` | Lyrebird + [DJI MSDK V5](https://github.com/dji-sdk/Mobile-SDK-Android-V5) | Lyrebird-APK (oder die DJI-Sample-App) im Container bauen |

Details zu Aufbau, Ports und Sicherheitsmodell: [docs/architektur.md](docs/architektur.md).
Bewertung aller SDU-UAS-Center-Repos und die Begründung, was eingebunden ist:
[docs/repo-bewertung.md](docs/repo-bewertung.md).

## Schnellstart

Voraussetzungen sind Linux mit Docker Engine und Compose v2. Der Rechner muss im selben (WLAN-)Netz wie die
Fernsteuerungen sein, weil die Drohnen per UDP-Broadcast gefunden werden.

```bash
git clone --recurse-submodules --shallow-submodules https://github.com/mason82-dotcom/DJI_GroundStation.git
```

```bash
cd DJI_GroundStation && ./scripts/bootstrap.sh
```

```bash
docker compose up -d --build
```

`bootstrap.sh` holt die gepinnten Submodules und legt `.env` an. Es fragt das Web-Passwort ab
(gespeichert wird nur der bcrypt-Hash) und erzeugt `./data`. Soll das eigene Netz ohne Login auskommen, dieses in `GS_LOGIN_EXEMPT` eintragen (siehe [Sicherheitsmodell](docs/architektur.md#sicherheitsmodell-und-offene-punkte)). Welche Teile laufen, steuert
`COMPOSE_PROFILES` in `.env`. Standard ist `archive,ros,dvm,agro,odm,qgc`.

Danach im Browser `https://<rechner>/` öffnen. Beim ersten Mal von jedem Gerät
`http://<rechner>/ca.crt` laden und als vertrauenswürdig importieren. Das ist die lokale CA von Caddy.

| Port | Oberfläche |
|---|---|
| 443 | Portal (Links, Endpunkte, QGC-Aktionen, CA-Zertifikat) |
| 8443 | Lyrebird-Flotten-Dashboard |
| 5443 | DVM |
| 4443 | QGroundControl |
| 6443 | QGIS + SDU Agro Tools |
| 7443 | Agro-Auswertung (API + Weboberfläche) |
| 3443 | NodeODM |
| 9443 | Datenarchiv (nur lesend) |

### Drohne verbinden

1. Lyrebird-App auf der Fernsteuerung installieren, entweder aus dem Upstream-Projekt oder über
   `docker compose run --rm android-build lyrebird` (DJI-App-Key in `.env` → `AIRCRAFT_API_KEY`).
   Die APK landet in `data/apk/`. Gegen eine andere DJI-MSDK-Version testen, ohne das Submodule
   zu ändern: `docker compose run --rm -e MSDK_VERSION=5.20.1 android-build lyrebird-check`
   (Debug-APK plus Unit-Tests in einer Arbeitskopie; ohne App-Key mit `ci-placeholder`).
2. App starten. Die Drohne erscheint automatisch im Dashboard, das ihr auch das Video-Ziel (WHIP) mitteilt.
3. **QGroundControl:** Verbindung `TCP <rechner>:5760` anlegen (über mavlink-router). QGC übernimmt
   die RTSP-Videoadresse von der Drohne selbst. Custom Actions (Takeoff, Land …) gibt es im Portal
   als `lyrebird-actions.json`.
4. **ROS 2:** Topics wie `/<drohne>/fmu/out/vehicle_global_position` auf `ROS_DOMAIN_ID`.
   Die Flotte wird in [`config/fleet_settings.yaml`](config/fleet_settings.yaml) eingestellt.

### Feldtest

Vor jedem Einsatz den Vorflugcheck laufen lassen. Er prüft Stack, Ports, Login, Speicher und jede gefundene Drohne
(Telemetrie, GPS, Akku, Video-Pfad). Er sendet nichts an die Drohne, und der Bericht landet in `data/fieldtest/<datum>/`:

```bash
./scripts/preflight.py
```

Danach die Phasen mit `docker compose run --rm gs-tools fieldtest <phase> <RC-IP>` durchgehen
(`link`, `ground`, `payload`, `ftp`, `signing`, `flight`); jede Phase wird protokolliert.
Ablauf, Rollen und Abbruchkriterien stehen in [docs/feldtest.md](docs/feldtest.md), die Vorlage zum
Ausdrucken in [docs/feldtest-protokoll.md](docs/feldtest-protokoll.md).

### Agrar-Workflow (Beispiel)

1. Feld abfliegen, dann landen. `media-sync` lädt die Fotos nach `data/media/<drohne>/`.
2. Agro-Auswertung (Port 7443) → Pipeline `odm-full` → Bildordner, Referenzbild und annotiertes
   Referenzbild wählen. Das Orthomosaik wird zusätzlich als `data/orthomosaics/odm-<id>.tif` abgelegt.
3. Ergebnis als ZIP herunterladen: Pflanzenreihen und gesunde bzw. kranke Segmente als Shapefiles. Oder
   alles im QGIS-Webdesktop (Port 6443) öffnen, wo `/data` ebenfalls eingebunden ist.

### Werkzeuge

```bash
docker compose run --rm gs-tools discover
```

```bash
docker compose run --rm gs-tools field-check <RC-IP> --phase ground
```

```bash
./scripts/pull-rc-logs.sh
```

`pull-rc-logs.sh` kopiert die JSONL- und DJI-TXT-Logs der Fernsteuerung per adb (USB). Die App gibt sie nicht übers Netz heraus.

## Repository-Aufbau

| Pfad | Inhalt |
|---|---|
| `compose.yaml` | der gesamte Stack, Profile siehe oben |
| `.env.example` | alle Einstellungen, kommentiert |
| `config/fleet_settings.yaml` | Flottenprofil für die ROS-Bridge (Kopie des Lyrebird-Standards) |
| `services/gs-init/` | rendert MediaMTX- und mavlink-router-Konfiguration aus `.env` (mit Tests) |
| `services/proxy/` | Caddyfile und Portalseite |
| `services/dashboard/` | Launcher, der das unveränderte Lyrebird-Dashboard auf 127.0.0.1 bindet |
| `services/media-sync/` | Medien- und Flug-Log-Archiv (mit Tests gegen eine simulierte Drohne) |
| `services/agro-api/` | FastAPI-Jobdienst für CDC, crop-row-detector, crop-row-connector und NodeODM (mit Tests) |
| `services/qgis/` | QGIS-Webdesktop mit SDU Agro Tools aus dem Submodule |
| `services/qgc/` | QGroundControl-Webdesktop (offizielles AppImage, Prüfsumme gepinnt) und Einstellungs-Vorbelegung (mit Tests) |
| `services/mavlink-router/`, `services/android-build/`, `services/gs-tools/` | Images bzw. Skripte |
| `scripts/` | `bootstrap`, `gen-password`, `preflight` (Vorflugcheck), `update-upstream`, `pull-rc-logs`, `check` |
| `upstream/` | Git-Submodules, gepinnt und unverändert (siehe unten) |

## Upstream und Lizenzen

Alle Fremdprojekte sind **Git-Submodules unter `upstream/`**, auf einen Commit gepinnt und nicht
verändert. Anpassungen liegen ausschließlich in `services/` und `config/`.

```bash
./scripts/update-upstream.sh
```

Das zeigt den gepinnten und den aktuellen Stand. Einen anderen Stand testest du mit
`./scripts/update-upstream.sh lyrebird onboard_mission_fixes`. Dieser Branch stellt den Missions-Executor
standardmäßig auf „onboard“ und markiert native DJI-Missionen als experimentell.

| Projekt | Lizenz | Hinweis |
|---|---|---|
| Lyrebird | **Business Source License 1.1** | Nur **nicht-produktive** Nutzung (Forschung, Entwicklung, Tests) ohne kommerzielle Lizenz; wird am 2028-08-31 zu MIT. Für Produktivbetrieb das SDU UAS Center kontaktieren. |
| DVM | MIT | |
| crop-row-connector | BSD-3-Clause | |
| sdu-agro-tools | GPL-2.0 | Läuft als eigenständiges QGIS-Plugin im Container |
| DJI Mobile SDK V5 | DJI EULA | Nur referenziert; das SDK lädt Gradle aus DJIs Maven-Repo, ein eigener App-Key ist nötig |
| CDC, crop-row-detector | BSD-3-Clause (PyPI) | |
| QGroundControl | Apache-2.0 / GPL-3.0 (Dual) | offizielles Release-AppImage, Version und SHA-256 je Architektur im Dockerfile gepinnt |
| MediaMTX (MIT), Caddy (Apache-2.0), mavlink-router (Apache-2.0), NodeODM (AGPL-3.0), QGIS (GPL-2.0+) | | als Images oder aus den Quellen gebaut |

Für die eigenen Dateien in diesem Repository ist noch keine Lizenz festgelegt.

## Entwicklung

```bash
./scripts/check.sh
```

`check.sh` prüft die Compose-Konfiguration für alle Profile und die Shell-Syntax. Außerdem laufen Tests und Lint
für `agro-api`, `media-sync`, `gs-init` und `qgc`. Dasselbe läuft in GitHub Actions
(`.github/workflows/ci.yml`).
