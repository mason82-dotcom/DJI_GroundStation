# Feldtest-Protokoll

Ablauf und Bedeutung der Prüfungen: [feldtest.md](feldtest.md). Ergebnis je Zeile: ✔ bestanden,
✘ fehlgeschlagen, – nicht geprüft. Bei ✘ Uhrzeit und Logdatei notieren.

## Rahmendaten

| | |
|---|---|
| Datum, Ort | |
| Wetter (Wind m/s, Temperatur) | |
| Pilot / GS-Operator / Beobachter | |
| Drohne (Modell, Seriennr., Name in Lyrebird) | |
| Fernsteuerung (Modell), Lyrebird-App-Version | |
| GroundStation `git rev-parse --short HEAD` | |
| Lyrebird-Submodule `git -C upstream/lyrebird rev-parse --short HEAD` | |
| Laptop / WLAN (Router, Kanal) | |
| Signing-Schlüssel gesetzt? | ja / nein |

## Phasen

| Phase | Prüfung | Ergebnis | Uhrzeit | Bemerkung / Logdatei |
|---|---|---|---|---|
| 2 | Vorflugcheck ohne FAIL | | | `fieldtest/…/preflight-…txt` |
| 3 | Link: Telemetrie kommt an, Position ≠ (0,0) | | | |
| 4 | QGC über TCP 5760 verbunden und stabil | | | |
| 4 | Flugmodus als Name; HUD bewegt sich | | | |
| 4 | QGC und `fieldtest link` gleichzeitig live | | | |
| 5 | RTH-Höhe geschrieben und über Telemetrie gelesen (Wert: ___ m) | | | |
| 5 | Nicht-numerischer Wert abgelehnt | | | |
| 6 | Gimbal −45° → Rücklesewert ___° | | | |
| 6 | Foto / Thermal / Temperatur / LRF / AutoSensing | | | |
| 6 | FTP-Liste = HTTP-Liste | | | |
| 6 | Signing: unsigniert abgelehnt nach Übernahme, Release nur signiert | | | |
| 7 | Dashboard-Video, Latenz ca. ___ s | | | |
| 7 | QGC-Video ohne Konfiguration | | | |
| 7 | Fotos im Archiv `media/<drohne>/` | | | |
| 8 | ROS-Topics `/…/fmu/out/…`, Position = QGC | | | |

## Flug

| # | Prüfung | Ergebnis | Uhrzeit | Bemerkung |
|---|---|---|---|---|
| R1 | QGC Go to location: fliegt **zum** Punkt | | | |
| R2 | QGC Change Altitude: ohne Drehung | | | |
| R3 | Goto hält Kurs (kein Drehen nach Norden) | | | |
| 1 | Start | | | |
| 2 | Starthöhe (angefordert ___ m, erreicht ___ m) | | | |
| 3 | gotoAltitude / gotoYaw Acks | | | |
| 4 | Manual Override stoppt, nächster Befehl abgelehnt | | | |
| 5 | Override aufgehoben | | | |
| 6 | Einzelner Wegpunkt, Latch einmal, seq ___ | | | |
| 7 | Ankunfts-Verweilzeit | | | |
| 8 | Hold-Heading | | | |
| 9 | Mehrteiliger Plan (___ Strecken) | | | |
| 10 | Halten vs. durchfliegen | | | |
| 11 | Ersetzen → SUPERSEDED | | | |
| 12 | Abbruch → CANCELLED | | | |
| 13 | RTH zum Home-Punkt | | | |
| 14 | ROS `transport: mavlink` end-to-end | | | |

Akkuwechsel / Flüge (Start–Landung, Akku % vorher → nachher):

| Flug | Start | Landung | Akku | Bemerkung |
|---|---|---|---|---|
| 1 | | | | |
| 2 | | | | |
| 3 | | | | |

## Nach der Landung

| Prüfung | Ergebnis | Bemerkung |
|---|---|---|
| Neue Medien von media-sync im Archiv | | |
| Telemetrie-Log pro Flug `flightlogs/<drohne>/<datum>/` | | |
| `.tlog` in `flightlogs/tlog/` | | |
| RC-Logs per `pull-rc-logs.sh` | | |
| Vorflugcheck am Ende | | |
| Archiv gesichert nach | | |

## Abweichungen (für Issues)

| Uhrzeit | Was passierte | Was erwartet war | Log / Datei |
|---|---|---|---|
| | | | |
| | | | |
