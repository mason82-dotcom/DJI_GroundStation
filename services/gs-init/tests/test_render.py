import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import render  # noqa: E402


def rendered(tmp_path, **env):
    render.render_dir(ROOT / "templates", tmp_path, render.build_context(env))
    return (tmp_path / "mediamtx.yml").read_text(), (tmp_path / "mavlink-router.conf").read_text()


def test_defaults_are_anonymous_lan_read(tmp_path):
    mtx, mav = rendered(tmp_path)
    assert "user: viewer" not in mtx and "apiAddress: 127.0.0.1:9997" in mtx
    assert "TcpServerPort = 5760" in mav and "Port = 14550" in mav and "Log = /logs" in mav


def test_named_viewer_needs_password(tmp_path):
    with pytest.raises(ValueError, match="MTX_READ_PASS"):
        render.build_context({"MTX_LAN_READ_ANONYMOUS": "false"})
    mtx, _ = rendered(tmp_path, MTX_LAN_READ_ANONYMOUS="false", MTX_READ_PASS="s3cret")
    assert "user: viewer\n    pass: s3cret" in mtx


def test_lists_and_extra_endpoint(tmp_path):
    mtx, mav = rendered(tmp_path, MTX_WEBRTC_INTERFACES="wlan0, eth1", MAVLINK_EXTRA_UDP_TARGET="10.8.0.2:14550", MAVLINK_LOG_ENABLED="false")
    assert "webrtcIPsFromInterfacesList: ['wlan0', 'eth1']" in mtx
    assert "[UdpEndpoint remote-gcs]\nMode = Normal\nAddress = 10.8.0.2\nPort = 14550" in mav
    assert "Log = /logs" not in mav


def test_empty_compose_values_keep_defaults():
    ctx = render.build_context({"MAVLINK_TCP_PORT": "", "MTX_PUBLISH_USER": ""})
    assert ctx["MAVLINK_TCP_PORT"] == "5760" and ctx["MTX_PUBLISH_USER"] == "any"


def test_bad_extra_target():
    with pytest.raises(ValueError):
        render.build_context({"MAVLINK_EXTRA_UDP_TARGET": "nohostport"})
