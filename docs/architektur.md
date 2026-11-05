# Architektur

```
 DJI-Drohne ── DJI-Funk ── Fernsteuerung mit Lyrebird-App (Android, MSDK V5)
                                │  WLAN / LAN
     ┌──────────────────────────┼───────────────────────────────────────────────────┐
     │ GroundStation-Host       │                                                   │
     │                          ├─ UDP 30000/30001  Discovery ◄── dashboard, ros, media-sync
     │                          ├─ UDP 14550  MAVLink ──► mavlink-router ──TCP 5760──► QGC/MAVSDK
     │                          │                       ◄─► dashboard (14552), ros (14561)
     │                          ├─ HTTP 8080 / TCP 8081 ◄── dashboard, ros, media-sync
     │                          └─ WHIP :8889 ──► mediamtx ──RTSP 8554──► QGC, ROS-Videonode
     │                                              └──WHEP (/mtx)──► Browser über Caddy
     │
     │  Caddy (Login + TLS) :443 Portal  :8443 Dashboard  :4443 QGC  :5443 DVM  :6443 QGIS
     │                      :7443 Agro   :3443 NodeODM    :9443 Archiv
     │
     │  ./data  ◄── media-sync (media/, flightlogs/), mavlink-router (flightlogs/tlog/)
     │          ──► QGIS, Agro-API, NodeODM-Jobs, Archiv-Browser
     └──────────────────────────────────────────────────────────────────────────────────┘
```

## Grundsätze

1. **Upstream bleibt unverändert.** Lyrebird, DVM, sdu-agro-tools, crop-row-connector und
   das DJI MSDK V5 sind gepinnte Submodules. Die Images entstehen aus deren eigenen Dockerfiles
   (Dashboard, ROS, ros-monitor) oder Quellen (Plugin, crop-row-connector-Wheel). Das Lyrebird-Dashboard
   bindet fest an `0.0.0.0`. `services/dashboard/bind_launcher.py` startet es deshalb unverändert, bindet es aber an
   `127.0.0.1`. Ein Patch im Submodule ist dafür nicht nötig.
2. **Ein Eingang für Menschen.** Alle Web-Oberflächen lauschen nur auf `127.0.0.1`. Caddy ist
   der einzige Dienst, der sie ins LAN bringt, immer mit Login (bcrypt) und TLS. Die lokale CA stellt
   Zertifikate on demand für jeden Hostnamen oder jede IP aus. Das ist im Feld wichtig, weil sich die IPs ändern.
3. **Host-Netz nur, wo die Drohne es verlangt.** Discovery per UDP-Broadcast, MAVLink zu jeder Drohne und
   WebRTC-UDP funktionieren nicht hinter Docker-NAT. Deshalb laufen `dashboard`, `ros`, `ros-monitor`,
   `media-sync`, `mediamtx`, `mavlink-router`, `gs-tools` und `proxy` im Host-Netz. Alle anderen Dienste
   laufen in Bridge-Netzen. DVMs Datenbank und Redis hängen in einem `internal`-Netz ohne Außenzugang.
   Grund: DVM hat Hostnamen und Passwort fest im Code.
4. **Ein Datenarchiv.** `GS_DATA_DIR` (Standard `./data`) ist für alle Dienste derselbe Ordner:

   | Ordner | geschrieben von | Inhalt |
   |---|---|---|
   | `media/<drohne>/` | media-sync | Fotos und Videos von der SD-Karte, `.synced.json` merkt sich den Stand |
   | `flightlogs/<drohne>/<datum>/` | media-sync | Telemetrie (TCP 8081) als JSONL, eine Datei pro Flug |
   | `flightlogs/tlog/` | mavlink-router | MAVLink-`.tlog`, solange eine Drohne „armed“ meldet |
   | `flightlogs/rc/<seriennr>/` | `scripts/pull-rc-logs.sh` | Lyrebird-JSONL und DJI-FlightRecords der Fernsteuerung |
   | `orthomosaics/` | Agro-API (ODM-Jobs) | fertige Orthomosaike als Eingabe für weitere Jobs und QGIS |
   | `agro-jobs/<id>/` | Agro-API | Eingaben, Ausgaben, Log und `job.json` jedes Jobs |
   | `apk/` | android-build | gebaute APKs |
   | `logs/dashboard/` | dashboard | Diagnose-Ereignisse des Lyrebird-Dashboards (NDJSON) |

## MAVLink: drei Bodenstationen nebeneinander

Ein UDP-Datagramm erreicht genau einen Socket. Lyrebird sendet deshalb an jede Station, von der es
etwas gehört hat (siehe Lyrebird-Doku *Running more than one ground station*):

| Station | lauscht | sendet an Drohne |
|---|---|---|
| mavlink-router (für QGC/MAVSDK über TCP 5760) | 14550 | 14550 |
| └ QGroundControl im Browser (`qgc`, System-ID **254**) | TCP 5760 am Router | über den Router |
| ROS-Flottenrouter (`config/fleet_settings.yaml` → `mavlink_port`) | 14561 | 14550 |
| Dashboard-MAVLink-Tab (`LB_WEBAPP_MAVLINK_PORT`) | 14552 | 14550 |

Den 1-Hz-Heartbeat-Broadcast der Drohnen empfängt der mavlink-router auf 14550. Sobald ein QGC-Client sich über TCP
verbindet, leitet der Router dessen Heartbeat an die Drohne weiter. Erst dann startet sie den vollen
Telemetriestrom. Ein QGC direkt auf diesem Rechner muss daher **TCP 5760** statt UDP 14550 nutzen.

### QGroundControl im Stack

Der Dienst `qgc` startet das offizielle QGC-AppImage in einem Webdesktop (wie QGIS) im Host-Netz.
`services/qgc/seed_settings.py` belegt beim Start die Einstellungen vor (Schlüssel aus dem QGC-Quellcode v5.1.5):

- feste TCP-Verbindung `127.0.0.1:5760` zum mavlink-router, **UDP-Autoconnect aus** – der Router belegt UDP 14550,
  ein zweites Lauschen dort würde Pakete abzweigen;
- **System-ID 254**: Dashboard und ROS-Bridge von Lyrebird senden als System 255 / Komponente 190. Laut
  MAVLink-Leitfaden (Routing) bekommen Bodenstationen absteigende IDs ab 255, damit Antworten zuordenbar bleiben;
- GCS-Heartbeat an (daran erkennt die Drohne eine Bodenstation), PX4/Multicopter als Vorauswahl, kein Ersteinrichtungsdialog.

Vom Nutzer in QGC geänderte Werte bleiben erhalten; erzwungen werden nur Router-Verbindung, UDP-Schalter und Heartbeat.
Signierte MAVLink-2-Pakete reicht der Router unverändert durch (MAVLink-Leitfaden).

## Video

Der Weg ist WHIP (App) → MediaMTX → WHEP (Browser) bzw. RTSP (QGC, ROS). Das Dashboard bekommt
`MEDIAMTX_WEBRTC_URL=/mtx`, damit der Browser das WHEP-Signalling über denselben authentifizierten
Ursprung schickt. Die Mediendaten fließen danach direkt per WebRTC-UDP (`MTX_WEBRTC_UDP_PORT`).

Lese-Rechte in MediaMTX:

- dieser Rechner (Caddy, Dashboard, ROS): immer
- LAN: `MTX_LAN_READ_ANONYMOUS=true` (Standard). QGC spielt die RTSP-Adresse, die die Drohne
  ankündigt, und die enthält keine Zugangsdaten. Mit `false` braucht man für RTSP im LAN Benutzer und Passwort
  (`MTX_READ_USER`/`MTX_READ_PASS`). Dann muss QGC das Video manuell mit Zugangsdaten konfigurieren.
- Veröffentlichen (WHIP/RTMP) ist im LAN offen, weil die Lyrebird-App ohne Zugangsdaten sendet.

## Sicherheitsmodell und offene Punkte

- **Login-Ausnahme fürs eigene Netz (optional):** `GS_LOGIN_EXEMPT` (CIDR-Liste) nimmt Clients aus diesen Netzen vom
  Web-Login aus; alle anderen – z. B. über VPN – brauchen ihn weiter. Standard: leer, also Login für alle. Wer das Heimnetz
  einträgt, erlaubt jedem Gerät darin die Bedienung von Dashboard und QGroundControl und damit von verbundenen Drohnen.

- **Nicht per Login geschützt** sind die Protokolle, die keine HTTP-Authentifizierung kennen oder die die Drohne
  selbst nutzt: MAVLink (UDP 14550, TCP 5760), MediaMTX-Ingest (8889, 8554, 1935, 8189/udp) und ROS 2 (DDS).
  Das entspricht Lyrebird upstream. Das Netz der Bodenstation ist damit die Vertrauensgrenze. Fremde
  Netze sollten nur über VPN oder eine Host-Firewall Zugang bekommen.
- **Zwei-Computer-Sicherheit** (Safety Computer per `X-Safety-Token` bzw. MAVLink-2-Signing)
  stellt Lyrebird in der App bereit. Getestet wird sie mit `gs-tools signing` bzw. `gs-tools authority`. Laut
  Lyrebird-Design gehört der Safety Computer auf **getrennte** Hardware.
- **Medien-Download** startet erst, wenn die Drohne `MEDIA_SYNC_LANDED_SECONDS` am Boden ist. Am Boden heißt:
  weniger als 1,5 m über dem Startpunkt und langsamer als 0,7 m/s. Lyrebird hat kein eigenes „in der
  Luft“-Feld. Im Flug braucht der Funk die Bandbreite für Steuerung und Video.
- **Lyrebird-Lizenz (BUSL-1.1):** Produktivbetrieb erfordert eine kommerzielle Lizenz des SDU UAS
  Center, bis die Lizenz am 2028-08-31 zu MIT wird.
