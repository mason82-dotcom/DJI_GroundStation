# Bewertung der SDU-UAS-Center-Repositories

Stand: 2026-11-05. Geprüft wurden alle öffentlichen Repositories von
<https://github.com/SDU-UAS-Center> sowie die Lyrebird-Dokumentation
(<https://sdu-uas-center.github.io/lyrebird/>, Quelle in `upstream/lyrebird/src/content/docs`).
Was eingebunden ist, wurde abgefragt und freigegeben.

| Repository | Sprache / Lizenz | letzte Aktivität | Entscheidung | Begründung |
|---|---|---|---|---|
| **lyrebird** | Kotlin, Python / BUSL-1.1 | 2026-10 | **Vorlage, eingebunden** | Kern: DJI ↔ MAVLink-2/HTTP-App, Dashboard, ROS 2, MediaMTX-Pipeline |
| **DVM** | Python (Flask, Celery) / MIT | 2026-10 | **eingebunden** (`dvm`) | Vermessen und Tracken in Drohnenvideos; fertiges Image `ghcr.io/sdu-uas-center/dvm:v2.1.0` |
| **sdu-agro-tools** | Python (QGIS-Plugin) / GPL-2.0 | 2026-10 | **eingebunden** (`agro`, QGIS-Webdesktop) | Installiert aus dem Quellcode wie im Abschnitt *Install from source code* der Installationsanleitung beschrieben; CDC, Crop Row Detector, Crop Row Connector |
| **crop-row-connector** | Python + Rust / BSD-3 | 2026-10 | **eingebunden** (`agro`, QGIS + Agro-API) | Wird aus dem Submodule gebaut (Rust 2024 via rustup) |
| VisionBasedPoseEstimation | Python / BSD-3 | 2026-01 | nicht eingebunden | Forschungscode (Visual SLAM, CLI), kein Dienst; später als Agro-API-Job möglich |
| n-fold-edge | Python / BSD-3 | 2026-06 | nicht eingebunden | Marker-Tracker; sinnvoll erst mit konkretem Marker- oder Landeplatz-Szenario |
| DroneID | Doku / CC BY 4.0 | 2016 | nicht eingebunden | Projektdokumentation, keine Software für den Stack |
| AutoQuad-SDU, AQ-MAVROS, AQ-LogReader | C / Python | 2017–2018 | nicht eingebunden | AutoQuad-Flugcontroller, veraltet (ROS Kinetic) |
| SDU-UAS-TX | C++ | 2018 | nicht eingebunden | Firmware für einen RC-Sender |
| LabEquipmentDrivers | Python | 2020 | nicht eingebunden | Laborgeräte-Treiber |

Zusätzlich auf Wunsch:

| Projekt | Lizenz | Einbindung |
|---|---|---|
| [dji-sdk/Mobile-SDK-Android-V5](https://github.com/dji-sdk/Mobile-SDK-Android-V5) | DJI EULA | Submodule; `android-build msdk-sample` baut die DJI-Sample-App, `android-build versions` vergleicht die MSDK-Version (Lyrebird 5.18.0, DJI aktuell 5.20.1) |
| OpenDroneMap / NodeODM | AGPL-3.0 | Image `opendronemap/nodeodm:3.6.2`; schließt die Lücke Fotos → Orthomosaik für die Agro-Pipeline |

## Erweiterungen aus der Lyrebird-Dokumentation

Aus der Doku abgeleitet und eingebaut:

- **Medien- und Log-Archiv** (`media-sync`): Lyrebird liefert SD-Karten-Medien über HTTP
  (`/send/listMedia`, `/send/downloadMediaByName`). Die JSONL- und DJI-TXT-Logs der Fernsteuerung liegen
  laut *Operations → Flight logging* nur auf dem Gerät und sind nicht übers Netz erreichbar. Deshalb gibt es
  ein bodenseitiges Telemetrie-Log pro Flug, `.tlog` über mavlink-router und `scripts/pull-rc-logs.sh` (adb).
- **GS-Tools**: `field_check.py` (Feldtest-Leitfaden), `signing_exercise.py`, `test_authority.py`
  (Zwei-Computer-Sicherheit), FTP- und Capture-Tests sowie die Flugbeispiele aus `GroundStation/examples`.
- **QGC Custom Actions**: `GroundStation/qgc/lyrebird-actions.json` zum Download im Portal.

Bewusst nicht eingebaut:

- **Safety-Computer als Dienst im Stack:** Laut Lyrebird-Design gehört er auf getrennte
  Hardware. Die Tests dafür liegen in `gs-tools`.
- **Lyrebird-Branch `onboard_mission_fixes`:** Dort ist der Missions-Executor standardmäßig „onboard“
  und native DJI-Missionen sind als experimentell markiert. Der Branch ist noch nicht in `main`. Umstellen geht mit
  `./scripts/update-upstream.sh lyrebird onboard_mission_fixes`.
