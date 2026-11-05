# Feldtest

Ablauf für den ersten Test des Stacks mit echter Drohne. Er folgt dem
[Lyrebird Field Test](https://sdu-uas-center.github.io/lyrebird/field-test/)
(`upstream/lyrebird/src/content/docs/field-test.md`) und ergänzt ihn um die Teile dieses Stacks:
Proxy, Video, mavlink-router, ROS, Archiv. Die ausfüllbare Vorlage für das Protokoll vor Ort ist
[feldtest-protokoll.md](feldtest-protokoll.md).

> Laut Lyrebird ist alles **außer dem Flug** auf dem Tisch gegen eine echte Drohne geprüft.
> Missions-Sequencer, Ankunfts-Verweilzeit, Steigflug nach dem Start und Positionsprüfung sind
> noch nie geflogen. Der erste Flug testet also den Sequencer, nicht die Wegpunkte.
> **Der Pilot hat während des gesamten Flugs die Daumen an den Sticks.**

Jede Phase hat eine Abbruchbedingung. Weiter geht es erst, wenn die Phase bestanden ist.

## Rollen

| Rolle | Aufgabe |
|---|---|
| **Pilot (Fernpilot)** | Fernsteuerung, jederzeit Übernahme per Sticks; entscheidet allein über Start, Abbruch und Landung |
| **GS-Operator** | Laptop: Vorflugcheck, `gs-tools`, QGC, Dashboard; spricht jeden Befehl vorher an |
| **Beobachter** | Luftraum und Umgebung, Sichtverbindung, Protokoll |

Für einen Test mit zwei Personen übernimmt der GS-Operator das Protokoll. Ein Pilot allein reicht nicht.

## 0. Vorher (zu Hause / im Büro)

**Rechtliches** (Deutschland/EU, keine Rechtsberatung):
- Betreiber beim LBA registriert, e-ID an der Drohne.
- Kompetenznachweis passend zur Klasse (A1/A3 bzw. A2).
- Haftpflichtversicherung vorhanden.
- Fluggebiet in der DIPUL-Karte geprüft: keine Geo-Zone ohne Genehmigung.
- Erlaubnis des Grundstückseigentümers.

**Software:**
- [ ] `git pull && git submodule update --init` – Stand notieren (`git rev-parse --short HEAD`)
- [ ] `docker compose up -d --build` **mit Internet** ausführen. Vor Ort gibt es oft keins; die Images müssen vorher fertig sein.
- [ ] Lyrebird-App: Die Version auf der Fernsteuerung passt zum gepinnten `upstream/lyrebird`. Bei Abweichung meldet sich der MAVLink-Dialekt durch **fehlende** Felder, nicht durch falsche. Das sieht aus wie ein schwacher Link, ist aber keiner. Neu bauen geht mit `docker compose run --rm android-build lyrebird`.
- [ ] Optional für Phase 6: In `.env` `LB_MAVLINK_SIGNING_KEY` setzen (64 Hex-Zeichen), in der App `lb_mav_0_signing_key` auf denselben Wert.
- [ ] `./scripts/check.sh` grün
- [ ] Einmal komplett im Büro: Stack starten, `./scripts/preflight.py` ohne Drohne. Erwartet: nur Warnungen unter *Drohnen*.

**Ausrüstung:**
- Akkus geladen: Drohne, Fernsteuerung, Laptop, Powerbank. Ersatzpropeller.
- Eigener WLAN-Router oder Hotspot. Fernsteuerung und Laptop müssen im selben Netz sein. Gast-WLANs mit Client-Isolation blockieren die UDP-Discovery.
- USB-Kabel für `adb`. Ausgedrucktes [Protokoll](feldtest-protokoll.md).

## 1. Aufbau vor Ort

1. Router an, Laptop ins WLAN; in `.env` `MTX_WEBRTC_INTERFACES=<wlan-schnittstelle>` setzen, falls der Laptop mehrere Netze hat (VPN, Docker, LTE).
2. `docker compose up -d`
3. Fernsteuerung ins WLAN, Lyrebird-App starten, Drohne einschalten, GPS-Fix abwarten.
4. Im Browser `https://<laptop-ip>/` öffnen (Login). Das Dashboard auf Port 8443 zeigt die Drohne.

## 2. Vorflugcheck – nur lesend

```bash
./scripts/preflight.py
```

Der Vorflugcheck prüft Stack, Ports, Login, MediaMTX, Speicher und Zeit. Für jede gefundene Drohne prüft er außerdem
HTTP `/config`, Telemetrie, Position, Satelliten, Akku und den Video-Pfad. Er sendet nichts an die Drohne. Der Bericht landet in
`data/fieldtest/<datum>/preflight-*.txt`.

**Abbruch:** Mindestens ein `FAIL`, oder Position `(0, 0)`. Warnungen bewerten:
- Akku unter 80 %: vor dem Flug tauschen.
- Weniger als 10 Satelliten: warten.
- Kein Video-Stream: in Phase 7 behandeln.

## 3. Link – sicher mit Propellern

```bash
docker compose run --rm gs-tools fieldtest link <RC-IP>
```

Das hört nur zu (eigener Port 14553) und sendet nichts außer dem GCS-Heartbeat.

Geprüft wird:
- Telemetrie kommt an.
- Die Kernfelder dekodieren.
- Die Konfiguration streamt.
- Die Position ist nicht `(0, 0)`.

Fehlende Werte für `homeLocation`, `remainingFlightTime` oder `distanceToHome` beschreiben den Zustand der Drohne, keinen Fehler der Schnittstelle.

**Abbruch:** `telemetry arrives` schlägt fehl. Dann prüfen: Ist die RC im selben WLAN? Gibt es Client-Isolation? Stimmt die App-Version?

## 4. QGroundControl sieht ein normales Fahrzeug

Es gibt eine Abweichung vom Lyrebird-Leitfaden: In diesem Stack belegt **mavlink-router** UDP 14550.
QGC verbindet sich deshalb über **TCP `<laptop-ip>:5760`** (Application Settings → Comm Links → TCP).

- [ ] Das Fahrzeug erscheint und bleibt verbunden, ohne „waiting for vehicle“.
- [ ] Position, Höhe, Kurs und Akku sind im HUD und bewegen sich.
- [ ] Der Flugmodus zeigt einen Namen, keine Zahl.
- [ ] **QGC und `gs-tools fieldtest link` laufen gleichzeitig**, beide live. Friert eines ein, teilen sie sich einen Port.
- [ ] Custom Actions laden: `lyrebird-actions.json` vom Portal.

**Abbruch:** QGC verbindet nicht oder verliert die Verbindung wiederholt.

## 5. Einstellungen am Boden

```bash
docker compose run --rm gs-tools fieldtest ground <RC-IP>
```

Das schreibt die RTH-Höhe und liest sie **über die Telemetrie** zurück. Außerdem muss ein nicht-numerischer
Wert *abgelehnt* werden. Gegenprobe im QGC-Parametereditor: `LB_RTH_ALT`, `LB_MAX_HEIGHT`, `LB_MAX_DIST`.
Die RTH-Höhe muss über allen Hindernissen im Fluggebiet liegen.

## 6. Nutzlast und Signing – der Gimbal bewegt sich

```bash
docker compose run --rm gs-tools fieldtest payload <RC-IP>
```

```bash
docker compose run --rm gs-tools fieldtest ftp <RC-IP>
```

```bash
docker compose run --rm gs-tools fieldtest signing <RC-IP>
```

Die Payload-Phase prüft Gimbal (absolut und relativ), Foto, Thermal, Temperatur, Entfernungsmesser und AutoSensing.

- **Gimbal:** Nach einem Befehl auf **−45°** muss der Rücklesewert nahe −45° liegen. Nahe **+45°** heißt, das Vorzeichen ist vertauscht.
- **Gimbal:** **6553.5** ist DJIs Marker für „nicht gesetzt“, kein Winkel.
- **AutoSensing:** Die Kamera auf eine Person richten. Null Treffer bei leerem Bild sagen nichts aus.
- **FTP:** Vergleicht die SD-Karten-Liste über MAVLink-FTP mit HTTP `/send/listMedia`.
- **Signing:** Nur mit gesetztem Schlüssel. Ein unsignierter Befehl muss abgelehnt werden, sobald ein signierter die Kontrolle an den Safety Computer gegeben hat. Nur ein signiertes Release gibt sie zurück. Lyrebird hat das nie mit einem echten Safety Computer geprüft. Am Ende die Kontrolle wieder freigeben (das Skript tut das in Schritt 4).

## 7. Video und Archiv am Boden

- [ ] **Dashboard** (Port 8443): Die Kachel zeigt Live-Video. Latenz mit Uhr oder Handbewegung schätzen und notieren (WHIP/WHEP: typisch unter 1 s).
- [ ] **QGC:** Das Video erscheint ohne Konfiguration, weil die Drohne die RTSP-Adresse ankündigt. Nach einer Umbenennung der Drohne QGC neu starten.
- [ ] Im Dashboard unter **MAVLink** *cross-check against HTTP* einschalten und **während des ganzen Flugs offen lassen.**
- [ ] **Archiv:** Unter Port 9443 gibt es `media/<drohne>/` mit den Fotos aus Phase 6. Das ist der Sync nach dem Verbinden. Das bestätigt den Download-Pfad.

## 8. ROS 2 (falls Profil `ros` aktiv)

```bash
docker compose exec ros bash -c 'source /opt/ros/$ROS_DISTRO/setup.bash && source /ros2_ws/install/setup.bash && ros2 topic list | grep fmu'
```

```bash
docker compose exec ros bash -c 'source /opt/ros/$ROS_DISTRO/setup.bash && source /ros2_ws/install/setup.bash && ros2 topic echo --once /<drohne>/fmu/out/vehicle_global_position'
```

- [ ] Topics sind vorhanden, die Position stimmt mit QGC überein.
- [ ] Das Dashboard zeigt den ROS-Status der Drohne. Diesen Bericht liefert `ros-monitor`.

## 9. Flug

```bash
docker compose run --rm gs-tools fieldtest flight <RC-IP>
```

Das gibt die Checkliste aus und protokolliert sie. Geflogen wird aus **QGC** oder mit den Flugbeispielen
(`gs-tools example …`, jeweils zuerst mit Dry-Run). Niedrig, langsam, mit Abstand zu Personen.
**Punkt 4 (Manual Override) vor allem prüfen, was darauf aufbaut.**

**Zuerst nachtesten:** Diese zwei QGC-Befehle sind beim ersten Lyrebird-Feldtest gescheitert und inzwischen behoben.
- **Go to location:** Die Drohne fliegt **zum** Punkt, mit Profil-Reisegeschwindigkeit. Früher floh sie mit −1 m/s.
- **Change Altitude:** Die Drohne steigt oder sinkt **ohne sich zu drehen**. Früher passierte nichts.
- Nach einem Goto hält die Drohne ihren Kurs. Früher drehte sie zum Schluss nach Norden.

| # | Prüfung | Bestanden, wenn |
|---|---|---|
| 1 | Start | `isFlying` wahr, Höhe steigt |
| 2 | Start**höhe** | angeforderte Höhe (`param7`) wird erreicht; Überschwingen nach DJIs Auto-Start beachten |
| 3 | `gotoAltitude` / `gotoYaw` | Ack `IN_PROGRESS`, dann erneut bei Ankunft |
| 4 | Manual Override | Sticks während eines Befehls: Bewegung stoppt; nächster Befehl wird *abgelehnt*; Landen, RTH und Abbruch bleiben verfügbar |
| 5 | Override aufheben | Kontrolle kommt zurück |
| 6 | Einzelner Wegpunkt | fliegt hin, `intermediaryWaypointReached` rastet **einmal** mit richtiger `seq` ein |
| 7 | Ankunfts-Verweilzeit | rastet dort ein, wo die Drohne wirklich ist, nicht mehrfach |
| 8 | Kurs halten | Hold-Heading: Kurs bleibt, kein Eindrehen in die Strecke |
| 9 | **Mehrteiliger Plan** | 2–3 Strecken, niedrig; in Reihenfolge, `MISSION_CURRENT` zählt hoch, nichts übersprungen (*größter ungetesteter Pfad*) |
| 10 | Halten vs. durchfliegen | hält, wo der Plan halten will; fliegt durch bei `param3` |
| 11 | Ersetzen | neuer Plan mitten in der Strecke: alter meldet `SUPERSEDED`, nicht `FAILED` |
| 12 | Abbruch | stoppt auf der Stelle, Ack `CANCELLED` |
| 13 | RTH | kehrt zurück und landet am Home-Punkt, in der Höhe aus Phase 5 |
| 14 | ROS mit `transport: mavlink` | eine Aktion end-to-end; sonst zurück auf `both` (`config/fleet_settings.yaml`) |

**Sofortiger Abbruch und Landung** bei:
- Verbindungsverlust länger als 3 s, Videoausfall bei Flug außer Sicht oder Akkuwarnung.
- Unerwarteter Richtung oder Drehung, oder einem Befehl, der „angenommen“ meldet, aber nicht ausgeführt wird.
- Jeder Abweichung, die der Pilot nicht sofort erklären kann.

Der Pilot übernimmt dann per Sticks. RTH nur, wenn der Rückweg frei ist.

> Laut Lyrebird wurde kein einziger MAVLink-Fehler durch Code-Lesen gefunden. Jeder war ein Frame,
> der sauber dekodierte und das Falsche bedeutete. Eine Abweichung im Dashboard-Tab **MAVLink**,
> die nur in der Luft auftritt, ist die interessante: ein Wert, der im Stand stimmt und bei Fahrt
> falsch ist oder sättigt. Uhrzeit notieren.

## 10. Nach der Landung

1. `media-sync` lädt neue Medien herunter, wenn die Drohne `MEDIA_SYNC_LANDED_SECONDS` (60 s) am Boden ist. Drohne und App so lange eingeschaltet lassen. Kontrolle unter Port 9443 → `media/<drohne>/`.
2. Prüfen, dass im Archiv angekommen ist:
   - `flightlogs/<drohne>/<datum>/*.jsonl`: ein Telemetrie-Log pro Flug, von Start bis Landung.
   - `flightlogs/tlog/`: MAVLink-Log, solange „armed“. Das gibt es nur, wenn QGC verbunden war.
   - `fieldtest/<datum>/`: Vorflugcheck und alle `gs-tools fieldtest`-Protokolle.
3. RC per USB anschließen. Dann holen die beiden Befehle unten die App-Logs (mit allen MAVLink-Befehlen samt Rohparametern) und die DJI-FlightRecords nach `flightlogs/rc/<seriennr>/`.
4. Vorflugcheck noch einmal laufen lassen (dokumentiert den Endzustand).
5. Archiv sichern, z. B. `rsync -a data/ <ziel>/` – **vor** dem nächsten Test.
6. Protokoll ausfüllen. Jede Abweichung mit Uhrzeit, Log-Datei und Erwartung als Issue anlegen.

```bash
./scripts/pull-rc-logs.sh
```

```bash
./scripts/preflight.py
```

## Optional: Agrar-Kette mit echten Daten

Ein Rasterflug über ein Feld, Fotos mit 70–80 % Überlappung (z. B. als QGC-Survey):
- `media-sync` holt die Fotos nach der Landung.
- In der Agro-Auswertung (Port 7443) die Pipeline `odm` auf `media/<drohne>` starten.
- Das Orthomosaik in QGIS (Port 6443) prüfen.
- Danach mit Referenzbild und Annotation die Pipeline `full` auf `orthomosaics/odm-*.tif` starten.

NodeODM braucht je nach Bildzahl Minuten bis Stunden; das passiert besser nach dem Feldtag.
