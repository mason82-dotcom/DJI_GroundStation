"""Media & flight-log archive for Lyrebird aircraft.

For every Lyrebird aircraft on the network this service

* records the aircraft's TCP telemetry stream (port 8081, newline-delimited JSON) into one
  JSONL file per flight under ``<data>/flightlogs/<drone>/<YYYY-MM-DD>/<HH-MM-SS>.jsonl`` --
  a ground-side flight log that exists even when the RC is lost or its storage is wiped;
* once the aircraft has been on the ground for a while, lists the SD card
  (``POST /send/listMedia``) and downloads every file it has not archived yet
  (``POST /send/downloadMediaByName``) into ``<data>/media/<drone>/``.

Nothing is downloaded while an aircraft is airborne: media transfer saturates the Wi-Fi link
(that is why Lyrebird keeps it on HTTP rather than MAVLink), and the link is needed for
control and video during the flight.

The archive is the shared ``/data`` volume, so DVM, the QGIS web desktop, NodeODM and the Agro
API see new photos and videos without copying.

Runs in the Lyrebird Python image (it uses the upstream ``lyrebird_groundstation`` discovery),
on the host network because discovery is a UDP broadcast.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

LOG = logging.getLogger("media-sync")

DATA_ROOT = Path(os.environ.get("MEDIA_SYNC_DATA_ROOT", "/data"))
HTTP_PORT = int(os.environ.get("LYREBIRD_HTTP_PORT", "8080"))
TELEMETRY_PORT = int(os.environ.get("TELEMETRY_PORT", "8081"))
DISCOVERY_INTERVAL = float(os.environ.get("MEDIA_SYNC_DISCOVERY_INTERVAL", "30"))
LANDED_SECONDS = float(os.environ.get("MEDIA_SYNC_LANDED_SECONDS", "60"))
AIRBORNE_ALTITUDE_M = float(os.environ.get("MEDIA_SYNC_AIRBORNE_ALTITUDE_M", "1.5"))
AIRBORNE_SPEED_MS = float(os.environ.get("MEDIA_SYNC_AIRBORNE_SPEED_MS", "0.7"))
DOWNLOAD_MEDIA = os.environ.get("MEDIA_SYNC_DOWNLOAD_MEDIA", "true").lower() == "true"
RECORD_TELEMETRY = os.environ.get("MEDIA_SYNC_RECORD_TELEMETRY", "true").lower() == "true"
STATIC_DRONES = os.environ.get("MEDIA_SYNC_DRONES", "")  # "name=ip,name2=ip2" for routed links
STATUS_BIND = os.environ.get("MEDIA_SYNC_STATUS_BIND", "127.0.0.1")
STATUS_PORT = int(os.environ.get("MEDIA_SYNC_STATUS_PORT", "17100"))

_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def safe_component(name: str, fallback: str = "unnamed") -> str:
    """One path component from an aircraft-supplied string (drone or file name).

    The aircraft is on the network, so its strings are untrusted: no separators, no ``..``,
    no hidden files, bounded length.
    """
    cleaned = _SAFE_NAME.sub("_", name.strip()).strip("._")
    return cleaned[:128] or fallback


def parse_static_drones(spec: str) -> dict[str, str]:
    drones = {}
    for item in spec.split(","):
        name, sep, ip = item.strip().partition("=")
        if sep and name.strip() and ip.strip():
            drones[ip.strip()] = name.strip()
    return drones


# --- flight state ------------------------------------------------------------------------------
def is_airborne(telemetry: dict) -> bool:
    """Heuristic: above AIRBORNE_ALTITUDE_M over take-off, or moving faster than walking pace.

    Lyrebird's TCP stream has no explicit in-air flag; altitude is reported relative to the
    take-off point (as in its MAVLink relative_alt), so a parked aircraft reads ~0 m.
    """
    location = telemetry.get("location") or {}
    altitude = location.get("altitude")
    if isinstance(altitude, (int, float)) and altitude > AIRBORNE_ALTITUDE_M:
        return True
    speed = telemetry.get("speed") or {}
    try:
        magnitude = math.sqrt(sum(float(speed.get(axis, 0.0)) ** 2 for axis in ("x", "y", "z")))
    except (TypeError, ValueError):
        return False
    return magnitude > AIRBORNE_SPEED_MS


@dataclass
class FlightTracker:
    """Debounced airborne/landed state for one aircraft."""

    landed_seconds: float = LANDED_SECONDS
    airborne: bool = False
    flight_started: float | None = None
    last_airborne: float | None = None
    pending_sync: bool = True  # sync once after (re)connecting, too

    def update(self, telemetry: dict, now: float) -> str | None:
        """Feed one sample; returns "takeoff", "landed" or None."""
        if is_airborne(telemetry):
            self.last_airborne = now
            if not self.airborne:
                self.airborne, self.flight_started = True, now
                return "takeoff"
            return None
        if self.airborne and self.last_airborne is not None and now - self.last_airborne >= self.landed_seconds:
            self.airborne, self.pending_sync = False, True
            return "landed"
        return None

    def should_sync(self) -> bool:
        return self.pending_sync and not self.airborne


# --- media -------------------------------------------------------------------------------------
def plan_downloads(listing: Iterable[dict], already: set[str]) -> list[str]:
    """Names on the SD card that are not archived yet, oldest index first."""
    files = [f for f in listing if isinstance(f, dict) and isinstance(f.get("name"), str)]
    files.sort(key=lambda f: (f.get("index", 0) if isinstance(f.get("index"), int) else 0, f["name"]))
    return [f["name"] for f in files if f["name"] not in already]


class MediaArchive:
    def __init__(self, root: Path, drone: str):
        self.dir = root / "media" / safe_component(drone)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.index_path = self.dir / ".synced.json"

    def synced(self) -> set[str]:
        try:
            return set(json.loads(self.index_path.read_text()))
        except (OSError, ValueError):
            return set()

    def mark(self, name: str) -> None:
        names = self.synced() | {name}
        tmp = self.index_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(sorted(names)))
        os.replace(tmp, self.index_path)

    def target(self, name: str) -> Path:
        return self.dir / safe_component(name)


def _post(ip: str, path: str, body: bytes = b"", timeout: float = 30.0):
    request = urllib.request.Request(f"http://{ip}:{HTTP_PORT}{path}", data=body, method="POST")
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - http to LAN aircraft


def sync_media(ip: str, drone: str, root: Path = DATA_ROOT) -> int:
    """Download every not-yet-archived SD-card file. Returns the number of new files."""
    archive = MediaArchive(root, drone)
    with _post(ip, "/send/listMedia") as response:
        listing = json.loads(response.read() or b"{}").get("files", [])
    new = 0
    for name in plan_downloads(listing, archive.synced()):
        target = archive.target(name)
        partial = target.with_name(target.name + ".part")
        try:
            with _post(ip, "/send/downloadMediaByName", name.encode(), timeout=600) as response:
                if "json" in response.headers.get("Content-Type", ""):
                    LOG.warning("%s: %s refused: %s", drone, name, response.read(200))
                    continue
                with partial.open("wb") as out:
                    while chunk := response.read(1024 * 1024):
                        out.write(chunk)
            os.replace(partial, target)
            archive.mark(name)
            new += 1
            LOG.info("%s: archived %s (%d bytes)", drone, target.name, target.stat().st_size)
        except (OSError, urllib.error.URLError) as error:
            partial.unlink(missing_ok=True)
            LOG.warning("%s: download of %s failed: %s", drone, name, error)
            break  # the link is probably gone; retry on the next landed cycle
    return new


# --- telemetry recording -----------------------------------------------------------------------
class FlightLogWriter:
    """One JSONL file per flight; samples are only written while a flight is open."""

    def __init__(self, root: Path, drone: str):
        self.base = root / "flightlogs" / safe_component(drone)
        self._file = None

    def open(self, when: datetime) -> Path:
        self.close()
        folder = self.base / when.strftime("%Y-%m-%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{when.strftime('%H-%M-%S')}.jsonl"
        self._file = path.open("a", encoding="utf-8")
        return path

    def write(self, telemetry: dict, received: datetime) -> None:
        if self._file is not None:
            self._file.write(json.dumps({"receivedAt": received.isoformat(), **telemetry}) + "\n")

    @property
    def is_open(self) -> bool:
        return self._file is not None

    def close(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None


@dataclass
class DroneWorker:
    ip: str
    name: str
    root: Path = DATA_ROOT
    tracker: FlightTracker = field(default_factory=FlightTracker)
    status: dict = field(default_factory=dict)
    stop: threading.Event = field(default_factory=threading.Event)

    def run(self) -> None:
        writer = FlightLogWriter(self.root, self.name)
        while not self.stop.is_set():
            try:
                self._session(writer)
            except OSError as error:
                self.status["lastError"] = str(error)
            writer.close()
            self.stop.wait(3)

    def _session(self, writer: FlightLogWriter) -> None:
        with socket.create_connection((self.ip, TELEMETRY_PORT), timeout=10) as sock:
            self.status.update(connected=True, lastError=None)
            buffer = b""
            sock.settimeout(10)
            while not self.stop.is_set():
                try:
                    chunk = sock.recv(65536)
                except TimeoutError:
                    self._maybe_sync()
                    continue
                if not chunk:
                    break
                buffer += chunk
                *lines, buffer = buffer.split(b"\n")
                for line in lines:
                    self._handle(line, writer)
                self._maybe_sync()
        self.status["connected"] = False

    def _handle(self, line: bytes, writer: FlightLogWriter) -> None:
        try:
            telemetry = json.loads(line)
        except ValueError:
            return
        if not isinstance(telemetry, dict):
            return
        now = datetime.now(UTC)
        event = self.tracker.update(telemetry, now.timestamp())
        if event == "takeoff" and RECORD_TELEMETRY:
            self.status["currentLog"] = str(writer.open(now.astimezone()))
            LOG.info("%s: take-off, recording %s", self.name, self.status["currentLog"])
        writer.write(telemetry, now)
        if event == "landed":
            writer.close()
            LOG.info("%s: landed", self.name)
        self.status.update(airborne=self.tracker.airborne, lastSample=now.isoformat())

    def _maybe_sync(self) -> None:
        if not DOWNLOAD_MEDIA or not self.tracker.should_sync():
            return
        self.tracker.pending_sync = False
        try:
            self.status["lastSyncNew"] = sync_media(self.ip, self.name, self.root)
            self.status["lastSync"] = datetime.now(UTC).isoformat()
        except (OSError, ValueError, urllib.error.URLError) as error:
            self.status["lastError"] = f"media sync: {error}"


class Service:
    def __init__(self, discover: Callable[[], dict[str, str]]):
        self._discover = discover
        self.workers: dict[str, DroneWorker] = {}

    def tick(self) -> None:
        for ip, name in self._discover().items():
            if ip in self.workers:
                continue
            worker = DroneWorker(ip=ip, name=name)
            worker.status.update(name=name, ip=ip)
            self.workers[ip] = worker
            threading.Thread(target=worker.run, name=f"drone-{name}", daemon=True).start()
            LOG.info("tracking %s at %s", name, ip)

    def snapshot(self) -> dict:
        return {"generatedAt": datetime.now(UTC).isoformat(), "drones": [w.status for w in self.workers.values()]}


def lyrebird_discover() -> dict[str, str]:
    from lyrebird_groundstation.discovery import discover_all

    found = {r.ip_address: r.name for r in discover_all(timeout=3.0, verbose=False, per_interface_broadcast=True)}
    found.update(parse_static_drones(STATIC_DRONES))
    return found


def serve_status(service: Service) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server API
            body = json.dumps(service.snapshot()).encode()
            self.send_response(200 if self.path in ("/", "/status") else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    ThreadingHTTPServer((STATUS_BIND, STATUS_PORT), Handler).serve_forever()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    service = Service(lyrebird_discover)
    threading.Thread(target=serve_status, args=(service,), daemon=True).start()
    LOG.info("media-sync: archive %s, media=%s, telemetry=%s", DATA_ROOT, DOWNLOAD_MEDIA, RECORD_TELEMETRY)
    while True:
        try:
            service.tick()
        except OSError as error:
            LOG.warning("discovery failed: %s", error)
        time.sleep(DISCOVERY_INTERVAL)


if __name__ == "__main__":
    main()
