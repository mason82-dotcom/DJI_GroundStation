import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import preflight as pf


def test_read_env_quotes_comments_and_dollar_escape(tmp_path):
    (tmp_path / ".env").write_text("# c\nA=1\nB='x y'\nGS_AUTH_HASH=$$2a$$14$$abc\nbad line\nC=\n")
    assert pf.read_env(tmp_path / ".env") == {"A": "1", "B": "x y", "GS_AUTH_HASH": "$2a$14$abc", "C": ""}


def test_udp_ports_from_proc_format(tmp_path):
    f = tmp_path / "udp"
    f.write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 00000000:38A6 00000000:0000 07\n"  # 14502
        "   1: 0100007F:1FFD 00000000:0000 07\n"  # 8189
    )
    assert pf.udp_listening_ports((str(f), str(tmp_path / "missing"))) == {0x38A6, 8189}


def statuses(sample):
    return {name: status for name, status, _ in pf.evaluate_telemetry(sample)}


def test_telemetry_evaluation():
    good = {
        "location": {"latitude": 55.37, "longitude": 10.43},
        "satelliteCount": 18,
        "batteryLevel": 95,
        "homeSet": True,
    }
    assert set(statuses(good).values()) == {pf.OK}
    bad = statuses({"location": {"latitude": 0.0, "longitude": 0.0}, "satelliteCount": 4, "batteryLevel": 30})
    assert bad == {"Position": pf.FAIL, "Satelliten": pf.WARN, "Akku": pf.FAIL}
    assert statuses({"isManualOverrideActive": True, "readyToTakeoff": False})["Manual Override"] == pf.WARN


def test_first_telemetry_reads_one_json_line():
    server = socket.create_server(("127.0.0.1", 0))

    def serve():
        conn, _ = server.accept()
        with conn:
            conn.sendall(b'garbage\n{"batteryLevel": 77}\n')

    threading.Thread(target=serve, daemon=True).start()
    assert pf.first_telemetry("127.0.0.1", server.getsockname()[1]) == {"batteryLevel": 77}
    assert pf.first_telemetry("127.0.0.1", 1, timeout=0.5) is None


def test_render_flags_failures():
    text = pf.render([pf.Result("Stack", "proxy", pf.OK), pf.Result("Ports", "x", pf.FAIL, "lauscht nicht")])
    assert "NICHT STARTEN" in text and "1 Fehler" in text
