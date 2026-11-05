#!/usr/bin/env python3
"""Vorflugcheck: prüft Stack und Drohnen vor einem Feldtest, ohne etwas zu senden.

Läuft auf dem GroundStation-Host (nur Python-Standardbibliothek)::

    ./scripts/preflight.py                 # Tabelle + Bericht unter data/fieldtest/<datum>/
    ./scripts/preflight.py --min-free-gb 50 --no-report

Geprüft wird, in dieser Reihenfolge:

1. Stack: alle Dienste der aktiven Profile laufen (und sind "healthy", wo es einen Healthcheck gibt)
2. Ports: Login-Proxy, Dashboard, MediaMTX, mavlink-router lauschen
3. Dienste: Portal verlangt Login, Dashboard-API, MediaMTX-API, media-sync-Status
4. Host: freier Speicher im Datenarchiv, Zeit synchronisiert, Netzwerkschnittstellen
5. Drohnen (vom Dashboard gefunden): HTTP /config, Telemetrie (GPS, Akku, Satelliten), Video-Pfad

Nichts davon bewegt eine Drohne oder ändert eine Einstellung: es werden nur GET-Anfragen und eine
lesende TCP-Verbindung zur Telemetrie (Port 8081) geöffnet.
Exit-Code 0 = keine Fehler (Warnungen erlaubt), 1 = mindestens ein Fehler.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OK, WARN, FAIL = "OK", "WARN", "FAIL"


@dataclass
class Result:
    group: str
    name: str
    status: str
    detail: str = ""


# --- helpers ---------------------------------------------------------------------------------
def read_env(path: Path) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE, comments, optional quotes; `$$` -> `$` like Compose."""
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        env[key.strip()] = value.replace("$$", "$")
    return env


def udp_listening_ports(proc_files=("/proc/net/udp", "/proc/net/udp6")) -> set[int]:
    """Local UDP ports with a bound socket (Linux /proc/net/udp format)."""
    ports: set[int] = set()
    for name in proc_files:
        try:
            lines = Path(name).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) > 1 and ":" in parts[1]:
                ports.add(int(parts[1].rsplit(":", 1)[1], 16))
    return ports


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get(url: str, timeout: float = 4.0) -> tuple[int, bytes]:
    """GET without following auth; TLS verification off only for the local self-signed proxy."""
    context = ssl._create_unverified_context() if url.startswith("https://127.0.0.1") else None
    request = urllib.request.Request(url, headers={"User-Agent": "gs-preflight"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


def evaluate_telemetry(sample: dict) -> list[tuple[str, str, str]]:
    """(check, status, detail) for one telemetry sample from TCP 8081."""
    checks = []
    loc = sample.get("location") or {}
    lat, lon = loc.get("latitude"), loc.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or (abs(lat) < 1e-6 and abs(lon) < 1e-6):
        checks.append(("Position", FAIL, f"keine gültige Position ({lat}, {lon})"))
    else:
        checks.append(("Position", OK, f"{lat:.6f}, {lon:.6f}"))
    sats = sample.get("satelliteCount")
    if isinstance(sats, int):
        checks.append(("Satelliten", OK if sats >= 10 else WARN, f"{sats} (≥10 empfohlen)"))
    else:
        checks.append(("Satelliten", WARN, "nicht gemeldet"))
    battery = sample.get("batteryLevel")
    if isinstance(battery, (int, float)):
        status = OK if battery >= 80 else WARN if battery >= 40 else FAIL
        checks.append(("Akku", status, f"{battery} % (Flugtest: ≥80 % empfohlen)"))
    else:
        checks.append(("Akku", WARN, "nicht gemeldet"))
    if sample.get("homeSet") is False:
        checks.append(("Home-Punkt", WARN, "noch nicht gesetzt (normal vor GPS-Fix)"))
    if sample.get("isManualOverrideActive"):
        checks.append(("Manual Override", WARN, "aktiv – autonome Befehle werden abgelehnt"))
    if sample.get("readyToTakeoff") is False:
        checks.append(("Startbereit", WARN, f"nein: {sample.get('takeoffBlockReason', '?')}"))
    return checks


def first_telemetry(ip: str, port: int, timeout: float = 6.0) -> dict | None:
    try:
        with socket.create_connection((ip, port), timeout=timeout) as sock:
            sock.settimeout(timeout)
            buffer = b""
            while b"\n" not in buffer and len(buffer) < 1_000_000:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                buffer += chunk
    except OSError:
        return None
    for line in buffer.split(b"\n"):
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


# --- checks ----------------------------------------------------------------------------------
def compose(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, check=False)


def check_stack(results: list[Result]) -> None:
    expected = compose("config", "--services")
    if expected.returncode != 0:
        results.append(Result("Stack", "docker compose", FAIL, expected.stderr.strip()[:200]))
        return
    oneshot = {"gs-init", "gs-tools", "android-build"}
    wanted = [s for s in expected.stdout.split() if s not in oneshot]
    ps = compose("ps", "--all", "--format", "json")
    states: dict[str, dict] = {}
    for line in ps.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        for entry in item if isinstance(item, list) else [item]:
            states[entry.get("Service", "")] = entry
    for service in wanted:
        entry = states.get(service)
        if entry is None:
            results.append(Result("Stack", service, FAIL, "nicht gestartet (docker compose up -d)"))
            continue
        state, health = entry.get("State", ""), entry.get("Health", "")
        if state != "running":
            results.append(Result("Stack", service, FAIL, f"{state} {entry.get('Status', '')}".strip()))
        elif health in ("unhealthy",):
            results.append(Result("Stack", service, FAIL, "unhealthy"))
        elif health == "starting":
            results.append(Result("Stack", service, WARN, "startet noch"))
        else:
            results.append(Result("Stack", service, OK, health or "running"))


def check_ports(results: list[Result], env: dict[str, str]) -> None:
    tcp = {
        "Portal (Caddy)": int(env.get("GS_PORT_PORTAL", 443)),
        "Dashboard (Caddy)": int(env.get("GS_PORT_DASHBOARD", 8443)),
        "MediaMTX WHIP/WHEP": 8889,
        "MediaMTX RTSP": 8554,
        "mavlink-router TCP (QGC)": int(env.get("MAVLINK_TCP_PORT", 5760)),
    }
    for name, port in tcp.items():
        ok = tcp_open("127.0.0.1", port)
        results.append(Result("Ports", f"{name} :{port}/tcp", OK if ok else FAIL, "" if ok else "lauscht nicht"))
    udp = udp_listening_ports()
    for name, port in {
        "MAVLink von Drohnen (mavlink-router)": int(env.get("MAVLINK_DRONE_PORT", 14550)),
        "WebRTC ICE (MediaMTX)": int(env.get("MTX_WEBRTC_UDP_PORT", 8189)),
    }.items():
        ok = port in udp
        results.append(Result("Ports", f"{name} :{port}/udp", OK if ok else FAIL, "" if ok else "kein Socket"))


def check_services(results: list[Result], env: dict[str, str]) -> list[dict]:
    try:
        status, _ = http_get(f"https://127.0.0.1:{env.get('GS_PORT_PORTAL', 443)}/")
        results.append(
            Result("Dienste", "Portal verlangt Login", OK if status == 401 else FAIL, f"HTTP {status} (erwartet 401)")
        )
    except OSError as error:
        results.append(Result("Dienste", "Portal verlangt Login", FAIL, f"nicht erreichbar: {error}"))
    drones: list[dict] = []
    port = env.get("GS_DASHBOARD_INTERNAL_PORT", "18090")
    try:
        status, body = http_get(f"http://127.0.0.1:{port}/api/drones")
        drones = json.loads(body or b"{}").get("drones", []) if status == 200 else []
        results.append(
            Result("Dienste", "Dashboard-API", OK if status == 200 else FAIL, f"HTTP {status}, {len(drones)} Drohne(n)")
        )
    except (OSError, ValueError) as error:
        results.append(Result("Dienste", "Dashboard-API", FAIL, str(error)))
    try:
        status, _ = http_get("http://127.0.0.1:9997/v3/paths/list")
        results.append(Result("Dienste", "MediaMTX-API", OK if status == 200 else FAIL, f"HTTP {status}"))
    except OSError as error:
        results.append(Result("Dienste", "MediaMTX-API", FAIL, str(error)))
    if "archive" in env.get("COMPOSE_PROFILES", ""):
        try:
            status, _ = http_get("http://127.0.0.1:17100/status")
            results.append(Result("Dienste", "media-sync", OK if status == 200 else FAIL, f"HTTP {status}"))
        except OSError as error:
            results.append(Result("Dienste", "media-sync", FAIL, str(error)))
    return drones


def check_host(results: list[Result], env: dict[str, str], min_free_gb: float) -> None:
    data = (ROOT / env.get("GS_DATA_DIR", "./data")).resolve()
    if not data.is_dir():
        results.append(Result("Host", "Datenarchiv", FAIL, f"{data} fehlt (scripts/bootstrap.sh)"))
    else:
        free = shutil.disk_usage(data).free / 1e9
        status = OK if free >= min_free_gb else WARN if free >= min_free_gb / 4 else FAIL
        results.append(Result("Host", "Freier Speicher Archiv", status, f"{free:.0f} GB frei (≥{min_free_gb:.0f} GB)"))
        writable = os.access(data, os.W_OK)
        results.append(Result("Host", "Archiv beschreibbar", OK if writable else FAIL, str(data)))
    sync = (
        subprocess.run(
            ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            check=False,
        )
        if shutil.which("timedatectl")
        else None
    )
    if sync is None or sync.returncode != 0:
        results.append(Result("Host", "Zeitsynchronisation", WARN, "nicht prüfbar (timedatectl)"))
    else:
        synced = sync.stdout.strip() == "yes"
        results.append(
            Result(
                "Host",
                "Zeitsynchronisation",
                OK if synced else WARN,
                "NTP synchron" if synced else "nicht synchron – Log-Zeitstempel prüfen",
            )
        )
    wanted = [i.strip() for i in env.get("MTX_WEBRTC_INTERFACES", "").split(",") if i.strip()]
    present = set(os.listdir("/sys/class/net")) if Path("/sys/class/net").is_dir() else set()
    for iface in wanted:
        results.append(
            Result(
                "Host",
                f"WebRTC-Schnittstelle {iface}",
                OK if iface in present else FAIL,
                "vorhanden" if iface in present else "nicht vorhanden – MTX_WEBRTC_INTERFACES prüfen",
            )
        )


def check_drones(results: list[Result], drones: list[dict], env: dict[str, str]) -> None:
    if not drones:
        results.append(Result("Drohnen", "Discovery", WARN, "keine Drohne gefunden – App gestartet, gleiches WLAN?"))
        return
    telemetry_port = int(env.get("TELEMETRY_PORT", 8081))
    for drone in drones:
        if drone.get("ignored"):
            continue
        name = drone.get("name") or "?"
        ip = drone.get("ip")
        group = f"Drohne {name}"
        if not ip:
            results.append(Result(group, "IP", FAIL, "keine IP bekannt"))
            continue
        try:
            status, body = http_get(f"http://{ip}:8080/config")
            config = json.loads(body or b"{}") if status == 200 else {}
            results.append(
                Result(
                    group,
                    f"HTTP /config ({ip})",
                    OK if status == 200 else FAIL,
                    f"meldet Name {config.get('droneName', config.get('name', '?'))!r}",
                )
            )
        except (OSError, ValueError) as error:
            results.append(Result(group, f"HTTP /config ({ip})", FAIL, str(error)))
        sample = first_telemetry(ip, telemetry_port)
        if sample is None:
            results.append(Result(group, "Telemetrie TCP 8081", FAIL, "keine Daten"))
        else:
            results.append(Result(group, "Telemetrie TCP 8081", OK, "Daten empfangen"))
            for check, status, detail in evaluate_telemetry(sample):
                results.append(Result(group, check, status, detail))
        stream = drone.get("streamName") or name
        try:
            status, body = http_get(f"http://127.0.0.1:9997/v3/paths/get/{urllib.request.quote(stream)}")
            ready = status == 200 and json.loads(body or b"{}").get("ready")
            results.append(
                Result(
                    group,
                    f"Video-Pfad '{stream}'",
                    OK if ready else WARN,
                    "Stream aktiv" if ready else "kein Stream (im Dashboard Video starten)",
                )
            )
        except (OSError, ValueError) as error:
            results.append(Result(group, f"Video-Pfad '{stream}'", WARN, str(error)))


# --- output ----------------------------------------------------------------------------------
def render(results: list[Result]) -> str:
    width = max((len(r.name) for r in results), default=10)
    lines, group = [], None
    for r in results:
        if r.group != group:
            group = r.group
            lines.append(f"\n== {group}")
        lines.append(f"  [{r.status:<4}] {r.name:<{width}}  {r.detail}")
    counts = {s: sum(r.status == s for r in results) for s in (OK, WARN, FAIL)}
    lines.append(f"\nErgebnis: {counts[OK]} OK, {counts[WARN]} Warnungen, {counts[FAIL]} Fehler")
    lines.append("=> FLUGTEST NICHT STARTEN" if counts[FAIL] else "=> bereit (Warnungen bewerten)")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vorflugcheck für Stack und Drohnen (nur lesend)")
    parser.add_argument("--min-free-gb", type=float, default=20.0)
    parser.add_argument("--no-report", action="store_true", help="keinen Bericht in data/fieldtest/ schreiben")
    args = parser.parse_args(argv)

    env = {**read_env(ROOT / ".env.example"), **read_env(ROOT / ".env")}
    results: list[Result] = []
    check_stack(results)
    check_ports(results, env)
    drones = check_services(results, env)
    check_host(results, env, args.min_free_gb)
    check_drones(results, drones, env)

    text = render(results)
    print(f"Vorflugcheck {datetime.now():%Y-%m-%d %H:%M:%S}{text}")
    if not args.no_report:
        folder = (ROOT / env.get("GS_DATA_DIR", "./data")).resolve() / "fieldtest" / f"{datetime.now():%Y-%m-%d}"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            stem = folder / f"preflight-{datetime.now():%H%M%S}"
            stem.with_suffix(".txt").write_text(text + "\n")
            stem.with_suffix(".json").write_text(json.dumps([asdict(r) for r in results], indent=2, ensure_ascii=False))
            print(f"\nBericht: {stem}.txt")
        except OSError as error:
            print(f"\nBericht nicht gespeichert: {error}", file=sys.stderr)
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
