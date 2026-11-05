# QGroundControl in the browser (noVNC), connected to the stack's mavlink-router.
#
# QGroundControl (github.com/mavlink/qgroundcontrol, Apache-2.0 / GPL-3.0) is a Qt desktop application. Like QGIS,
# the stack runs the official release inside Xvfb and exposes it through noVNC behind the authenticated Caddy proxy
# (port GS_PORT_QGC). The official AppImage is used instead of a source build (Qt 6 toolchain, ~1 h); it is pinned
# by version and SHA-256 per architecture and extracted at build time, so no FUSE is needed at runtime.
#
# The container runs in the host network: QGC connects to mavlink-router over TCP 127.0.0.1:5760 and plays the
# RTSP URL the drone announces. UDP auto-connect is switched off by seed_settings.py because mavlink-router owns
# UDP 14550; QGC's GCS system ID is 254 (Lyrebird dashboard/ROS use 255).
FROM ubuntu:24.04

ARG QGC_VERSION=v5.1.5
ARG QGC_SHA256_AMD64=9a47e4cf269d9e4f897f582f6b19aa7ebf1e9e67c9d68a532a45b541354bc344
ARG QGC_SHA256_ARM64=ddd92fe3a1cd1c1c21a3028052e9f9b4d4a68cb80689552d3f34727ed2c91e03
# Settings schema version of this QGC release (QGC_SETTINGS_VERSION in its CMakeLists.txt). QGC wipes its settings
# file when the stored version differs, so the seeder writes exactly this value. Change all four ARGs together.
ARG QGC_SETTINGS_VERSION=9
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    DISPLAY=:2 \
    HOME=/home/qgc \
    XDG_RUNTIME_DIR=/tmp/runtime-qgc \
    QT_QPA_PLATFORM=xcb \
    VNC_GEOMETRY=1920x1080 \
    XAUTHORITY=/tmp/runtime-qgc/Xauthority
ENV QGC_SETTINGS_VERSION=${QGC_SETTINGS_VERSION}

# Runtime dependencies for Qt (xcb/xkb, OpenGL via Mesa llvmpipe) plus the web-desktop pieces used by the QGIS
# service. No system GStreamer: the AppImage bundles its plugins (rtsp, rtp, libav, openh264, ...) and AppRun points
# GST_PLUGIN_SYSTEM_PATH at them exclusively. xauth/mcookie protect the X display (host network, see entrypoint).
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc x11-utils xauth util-linux novnc websockify openbox fonts-dejavu-core procps ca-certificates \
        curl python3 \
        libgl1 libegl1 libgl1-mesa-dri libglu1-mesa libxkbcommon-x11-0 libxcb-cursor0 libxcb-xinerama0 libxcb-icccm4 libxcb-image0 \
        libxcb-keysyms1 libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinput0 libpulse0 libsdl2-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    case "${TARGETARCH:-amd64}" in \
      amd64) arch=x86_64;  sum="${QGC_SHA256_AMD64}" ;; \
      arm64) arch=aarch64; sum="${QGC_SHA256_ARM64}" ;; \
      *) echo "unsupported architecture ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL -o /tmp/qgc.AppImage \
      "https://github.com/mavlink/qgroundcontrol/releases/download/${QGC_VERSION}/QGroundControl-${arch}.AppImage"; \
    echo "${sum}  /tmp/qgc.AppImage" | sha256sum -c -; \
    chmod +x /tmp/qgc.AppImage; \
    cd /opt && /tmp/qgc.AppImage --appimage-extract >/dev/null && mv squashfs-root qgc && rm /tmp/qgc.AppImage; \
    # The extracted tree is root-only (squashfs-root is 0700); the runtime user needs read/execute, never write.
    chmod -R a+rX,go-w /opt/qgc; \
    test -x /opt/qgc/AppRun

RUN (userdel -r ubuntu 2>/dev/null || true) \
    && useradd --create-home --home-dir /home/qgc --uid 1000 --shell /bin/bash qgc

COPY services/qgc/seed_settings.py /usr/local/bin/gs-qgc-seed
COPY services/qgc/entrypoint.sh /usr/local/bin/gs-qgc-entrypoint
COPY services/qgc/openbox-rc.xml /etc/gs-qgc/openbox-rc.xml
RUN chmod 0755 /usr/local/bin/gs-qgc-seed /usr/local/bin/gs-qgc-entrypoint

USER qgc
WORKDIR /home/qgc
# Healthy only if noVNC answers AND QGroundControl itself runs (a crash loop must not look healthy).
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD pgrep -f /opt/qgc/usr/bin/QGroundControl >/dev/null && python3 -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('NOVNC_PORT', '16081') + '/vnc.html', timeout=4)"
ENTRYPOINT ["/usr/local/bin/gs-qgc-entrypoint"]
