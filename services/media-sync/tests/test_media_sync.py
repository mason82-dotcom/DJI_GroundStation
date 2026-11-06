import json
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import media_sync as ms  # noqa: E402


def sample(alt=0.0, vx=0.0):
    return {"droneName": "mini", "location": {"latitude": 55.0, "longitude": 10.0, "altitude": alt}, "speed": {"x": vx, "y": 0, "z": 0}}


def test_safe_component_blocks_traversal():
    assert ms.safe_component("../../etc/passwd") == "etc_passwd"
    assert ms.safe_component("DJI_0001.JPG") == "DJI_0001.JPG"
    assert ms.safe_component("..") == "unnamed"
    assert ms.safe_component(".hidden") == "hidden"


def test_airborne_heuristic():
    assert not ms.is_airborne(sample(0.2))
    assert ms.is_airborne(sample(5.0))
    assert ms.is_airborne(sample(0.0, vx=3.0))
    assert not ms.is_airborne({"speed": {"x": "bad"}})


def test_tracker_debounces_landing():
    t = ms.FlightTracker(landed_seconds=10)
    assert t.should_sync()  # sync once after connecting
    t.pending_sync = False
    assert t.update(sample(10), 0) == "takeoff"
    assert not t.should_sync()
    assert t.update(sample(0), 5) is None  # touched down, not settled yet
    assert t.update(sample(0), 11) == "landed"
    assert t.should_sync()


def test_plan_downloads_skips_archived_and_orders_by_index():
    listing = [{"name": "B.JPG", "index": 2}, {"name": "A.JPG", "index": 1}, {"name": "C.MP4", "index": 3}, {"bad": 1}]
    assert ms.plan_downloads(listing, {"B.JPG"}) == ["A.JPG", "C.MP4"]


def test_parse_static_drones():
    assert ms.parse_static_drones("m3=10.0.0.5, m4 = 10.0.0.6,,bad") == {"10.0.0.5": "m3", "10.0.0.6": "m4"}


class FakeDrone:
    """HTTP (listMedia/downloadMediaByName) and TCP telemetry like the Lyrebird app."""

    files = {"DJI_0001.JPG": b"jpeg-bytes", "DJI_0002.MP4": b"mp4-bytes" * 1000, "../evil": b"x"}

    def __init__(self, samples):
        drone = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode()
                if self.path == "/send/listMedia":
                    payload, ctype = json.dumps({"files": [{"name": n, "index": i} for i, n in enumerate(drone.files)]}).encode(), "application/json"
                elif self.path == "/send/downloadMediaByName" and body in drone.files:
                    payload, ctype = drone.files[body], "application/octet-stream"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *a):
                pass

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.tcp = socket.create_server(("127.0.0.1", 0))
        self.samples = samples
        threading.Thread(target=self.http.serve_forever, daemon=True).start()
        threading.Thread(target=self._telemetry, daemon=True).start()

    def _telemetry(self):
        conn, _ = self.tcp.accept()
        with conn:
            try:
                for s in self.samples:
                    conn.sendall((json.dumps(s) + "\n").encode())
                    time.sleep(0.02)
                time.sleep(2)
            except OSError:
                pass  # the worker under test disconnected first


def test_worker_records_flight_and_archives_media_after_landing(tmp_path, monkeypatch):
    samples = [sample(0)] + [sample(20)] * 5 + [sample(0)] * 20
    drone = FakeDrone(samples)
    monkeypatch.setattr(ms, "HTTP_PORT", drone.http.server_address[1])
    monkeypatch.setattr(ms, "TELEMETRY_PORT", drone.tcp.getsockname()[1])
    worker = ms.DroneWorker(ip="127.0.0.1", name="mini/../x", root=tmp_path, tracker=ms.FlightTracker(landed_seconds=0.1))
    worker.tracker.pending_sync = False  # only the post-landing sync is under test
    threading.Thread(target=worker.run, daemon=True).start()
    deadline = time.time() + 10
    media = tmp_path / "media" / "mini_.._x"
    index = media / ".synced.json"

    def all_synced():  # the index is rewritten atomically after each finished download
        try:
            return set(json.loads(index.read_text())) == set(FakeDrone.files)
        except (OSError, ValueError):
            return False

    while time.time() < deadline and not all_synced():
        time.sleep(0.05)
    worker.stop.set()

    assert (media / "DJI_0001.JPG").read_bytes() == b"jpeg-bytes"
    assert (media / "DJI_0002.MP4").stat().st_size == 9000
    assert (media / "evil").exists() and not (tmp_path / "evil").exists()
    assert all_synced()
    logs = list((tmp_path / "flightlogs").rglob("*.jsonl"))
    assert len(logs) == 1
    lines = [json.loads(line) for line in logs[0].read_text().splitlines()]
    assert lines[0]["location"]["altitude"] == 20 and "receivedAt" in lines[0]

    # a second sync downloads nothing new
    assert ms.sync_media("127.0.0.1", "mini/../x", tmp_path) == 0
