"""Run the unmodified Lyrebird dashboard (server.py) bound to one address instead of 0.0.0.0.

Upstream ``GroundStation/video_test/webapp/server.py`` hard-codes ``ThreadingHTTPServer(("0.0.0.0",
PORT), ...)``. The dashboard has to share the host network (UDP broadcast discovery of the
aircraft, MAVLink to each aircraft), so publishing ports cannot limit who reaches it. This
launcher replaces ``http.server.ThreadingHTTPServer`` with a subclass that keeps the port but
binds ``GS_BIND_HOST`` (default ``127.0.0.1``) before running server.py as ``__main__``. The
authenticated Caddy proxy is then the only way in from the network, and the Lyrebird submodule
stays untouched.

Usage (container CMD)::

    python /gs/bind_launcher.py server.py
"""

from __future__ import annotations

import http.server
import os
import runpy
import sys

BIND_HOST = os.environ.get("GS_BIND_HOST", "127.0.0.1")
_Original = http.server.ThreadingHTTPServer


class _BoundThreadingHTTPServer(_Original):
    def __init__(self, server_address, handler_class, bind_and_activate=True):
        _host, port = server_address[0], server_address[1]
        super().__init__((BIND_HOST, port), handler_class, bind_and_activate)


def main(argv: list[str]) -> None:
    if len(argv) < 2:
        raise SystemExit("usage: bind_launcher.py <script.py> [args...]")
    http.server.ThreadingHTTPServer = _BoundThreadingHTTPServer
    script = os.path.abspath(argv[1])
    sys.argv = argv[1:]
    # `python script.py` puts the script's folder first on sys.path; run_path does not.
    sys.path.insert(0, os.path.dirname(script))
    print(f"[gs] binding {script} HTTP server to {BIND_HOST}", flush=True)
    runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main(sys.argv)
