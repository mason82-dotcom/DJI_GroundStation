#!/usr/bin/env python3
"""Seed and enforce QGroundControl settings for the ground-station stack.

QGroundControl (v5.1.x) keeps its settings in ``~/.config/QGroundControl/QGroundControl.ini``
(organisation and application name "QGroundControl", settings schema version 9 – a different
``SettingsVersion`` makes QGC wipe the file on start).

Inside the stack QGC runs in the host network next to mavlink-router, which already owns UDP 14550.
QGC must therefore NOT auto-listen on UDP (``[AutoConnect] autoConnectUDP``) and instead use one TCP
link to the router (``127.0.0.1:5760``), which also forwards QGC's heartbeat so the drone starts the full
telemetry stream (see docs/architektur.md). Keys follow src/Comms/LinkManager.cc and TCPLink.cc of
QGroundControl v5.1.5; link type 2 = TCP in desktop builds (serial link compiled in).

MAVLink identity (MAVLink guide, routing: ground stations get system IDs counting down from 255): the Lyrebird
dashboard and ROS bridge already send as system 255 / component 190, which is also QGC's default. QGC is seeded
with system ID 254 (``gcsMavlinkSystemID``, top-level group) so the drone can tell the stations apart; a value the
user later sets in QGC is kept. ``sendGCSHeartbeat`` stays on: the heartbeat is how the drone sees a ground station.

First start: Lyrebird presents the drone as a PX4 multicopter, so the vehicle preferences are seeded with
``preferredFirmwareClass=12`` (PX4 Pro) and ``preferredVehicleClass=2`` (Multi-Rotor) and the initial-setup prompt
(id 3, ``firstRunPromptIdsShown``) is marked as shown; QGC's units default to metric already. All three only
when absent, so a choice made in QGC is kept.

Idempotent: existing user settings stay, only the router link, the UDP switch and the heartbeat are enforced.
"""

from __future__ import annotations

import argparse
import configparser
import os
import tempfile
from io import StringIO
from pathlib import Path

SETTINGS_VERSION = "9"
DEFAULT_SYSTEM_ID = 254
LINK_TYPE_TCP = "2"
ROUTER_LINK_NAME = "GroundStation (mavlink-router)"


def _parser() -> configparser.ConfigParser:
    cp = configparser.ConfigParser(interpolation=None, delimiters=("=",))
    cp.optionxform = str  # QSettings keys are case-sensitive
    return cp


def seed(
    path: Path,
    host: str = "127.0.0.1",
    port: int = 5760,
    system_id: int = DEFAULT_SYSTEM_ID,
    settings_version: str = SETTINGS_VERSION,
    save_path: str | None = None,
) -> bool:
    """Write or update the settings file. Returns True if the file changed."""
    cp = _parser()
    before = ""
    if path.exists():
        before = path.read_text(encoding="utf-8")
        cp.read_string(before)

    if not cp.has_section("General"):
        cp.add_section("General")
    # Exactly the schema version of the installed QGC: any other value makes QGC wipe the whole file on start,
    # which would bring back UDP auto-connect on 14550 next to mavlink-router.
    cp["General"]["SettingsVersion"] = str(settings_version)
    if not 1 <= system_id <= 255:
        raise ValueError("MAVLink system ID must be 1..255")
    cp["General"].setdefault("gcsMavlinkSystemID", str(system_id))
    cp["General"]["sendGCSHeartbeat"] = "true"
    cp["General"].setdefault("preferredFirmwareClass", "12")  # PX4 Pro
    cp["General"].setdefault("preferredVehicleClass", "2")  # Multi-Rotor
    cp["General"].setdefault("firstRunPromptIdsShown", "3")  # initial setup prompt
    if save_path:
        # Telemetry logs, plans and videos into the shared data archive instead of the home volume.
        cp["General"].setdefault("savePath", save_path)

    if not cp.has_section("AutoConnect"):
        cp.add_section("AutoConnect")
    cp["AutoConnect"]["autoConnectUDP"] = "false"

    if not cp.has_section("LinkConfigurations"):
        cp.add_section("LinkConfigurations")
    links = cp["LinkConfigurations"]
    count = int(links.get("count", "0") or 0)
    index = next(
        (i for i in range(count) if links.get(f"Link{i}\\name") == ROUTER_LINK_NAME),
        count,
    )
    links[f"Link{index}\\name"] = ROUTER_LINK_NAME
    links[f"Link{index}\\type"] = LINK_TYPE_TCP
    links[f"Link{index}\\auto"] = "true"
    links[f"Link{index}\\high_latency"] = "false"
    links[f"Link{index}\\host"] = host
    links[f"Link{index}\\port"] = str(port)
    links["count"] = str(max(count, index + 1))

    out = StringIO()
    cp.write(out, space_around_delimiters=False)
    after = out.getvalue()
    if after == before:
        return False
    # Atomic replace: a stop during the write must never leave a truncated file (QGC would reset everything).
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(
        dir=path.parent, prefix=".QGroundControl.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(after)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return True


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--settings",
        type=Path,
        default=Path.home() / ".config/QGroundControl/QGroundControl.ini",
    )
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5760)
    ap.add_argument("--system-id", type=int, default=DEFAULT_SYSTEM_ID)
    ap.add_argument("--settings-version", default=SETTINGS_VERSION)
    ap.add_argument("--save-path", default=None)
    args = ap.parse_args()
    changed = seed(
        args.settings,
        args.host,
        args.port,
        args.system_id,
        args.settings_version,
        args.save_path,
    )
    print(f"[qgc] settings {'updated' if changed else 'unchanged'}: {args.settings}")


if __name__ == "__main__":
    main()
