"""Render the stack's config templates from environment variables.

Runs once as the ``gs-init`` container before the services that read the rendered
files (MediaMTX, mavlink-router). Templates use ``${NAME}`` placeholders
(``string.Template``); every placeholder must be set, so a typo in ``.env`` fails
the stack at start-up instead of shipping an empty password or port.

Usage::

    python render.py <template-dir> <output-dir>

Each ``<name>.tmpl`` in the template directory becomes ``<name>`` in the output
directory. Only the standard library is used, so the stock ``python:*-slim`` image
is enough.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from string import Template

DEFAULTS = {
    "MTX_READ_USER": "viewer",
    "MTX_READ_PASS": "",
    # QGroundControl takes the RTSP address the aircraft advertises (VIDEO_STREAM_INFORMATION),
    # which carries no credentials, so LAN reads are anonymous unless this is set to false.
    "MTX_LAN_READ_ANONYMOUS": "true",
    "MTX_PUBLISH_USER": "any",
    "MTX_PUBLISH_PASS": "",
    "MTX_WEBRTC_ADDITIONAL_HOSTS": "",
    "MTX_WEBRTC_UDP_PORT": "8189",
    "MTX_WEBRTC_INTERFACES": "",
    "MAVLINK_DRONE_PORT": "14550",
    "MAVLINK_TCP_PORT": "5760",
    "MAVLINK_LOG_ENABLED": "true",
    "MAVLINK_EXTRA_UDP_TARGET": "",
}


def yaml_list(csv: str) -> str:
    """Turn ``a, b`` into a YAML flow list ``['a', 'b']`` (empty -> ``[]``)."""
    items = [item.strip() for item in csv.split(",") if item.strip()]
    return "[" + ", ".join(f"'{item}'" for item in items) + "]"


def mavlink_extra_endpoint(target: str) -> str:
    """Optional extra UDP endpoint ``host:port`` for a remote ground station."""
    if not target.strip():
        return ""
    host, _, port = target.strip().rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"MAVLINK_EXTRA_UDP_TARGET must be host:port, got {target!r}")
    return f"[UdpEndpoint remote-gcs]\nMode = Normal\nAddress = {host}\nPort = {port}\n"


def build_context(env: dict[str, str]) -> dict[str, str]:
    # Compose passes an unset variable as "", so only non-empty values override defaults.
    ctx = {**DEFAULTS, **{k: v for k, v in env.items() if v}}
    if ctx["MTX_LAN_READ_ANONYMOUS"].lower() == "true":
        ctx["MTX_VIEWER_USER"], ctx["MTX_VIEWER_PASS"] = "any", ""
    else:
        if not ctx["MTX_READ_PASS"]:
            raise ValueError("MTX_READ_PASS is empty: set it in .env (scripts/bootstrap.sh generates one)")
        ctx["MTX_VIEWER_USER"], ctx["MTX_VIEWER_PASS"] = ctx["MTX_READ_USER"], ctx["MTX_READ_PASS"]
    ctx["MTX_WEBRTC_ADDITIONAL_HOSTS_YAML"] = yaml_list(ctx["MTX_WEBRTC_ADDITIONAL_HOSTS"])
    ctx["MTX_WEBRTC_INTERFACES_YAML"] = yaml_list(ctx["MTX_WEBRTC_INTERFACES"])
    ctx["MAVLINK_LOG_LINE"] = "Log = /logs" if ctx["MAVLINK_LOG_ENABLED"].lower() == "true" else ""
    ctx["MAVLINK_EXTRA_ENDPOINT"] = mavlink_extra_endpoint(ctx["MAVLINK_EXTRA_UDP_TARGET"])
    return ctx


def render_dir(template_dir: Path, output_dir: Path, ctx: dict[str, str]) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for template in sorted(template_dir.glob("*.tmpl")):
        target = output_dir / template.name.removesuffix(".tmpl")
        target.write_text(Template(template.read_text()).substitute(ctx))
        target.chmod(0o644)
        written.append(target)
    if not written:
        raise FileNotFoundError(f"no *.tmpl files in {template_dir}")
    return written


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        ctx = build_context(dict(os.environ))
        for path in render_dir(Path(argv[1]), Path(argv[2]), ctx):
            print(f"[gs-init] rendered {path}")
    except (KeyError, ValueError, FileNotFoundError) as error:
        print(f"[gs-init] ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
