# QGIS desktop in the browser (noVNC) with SDU Agro Tools installed from source.
#
# sdu-agro-tools (GPL-2.0, upstream/sdu-agro-tools) is a QGIS desktop plugin, not a server
# component, so the stack runs a full QGIS inside Xvfb and exposes it through noVNC behind the
# authenticated Caddy proxy. The plugin is deployed the way its "Install from source code"
# guide describes (`make deploy` into the profile's python/plugins folder), and its Python
# dependencies are installed into QGIS' own interpreter at build time instead of through the
# interactive qpip plugin.
#
# Headless use is possible too, through QGIS' processing CLI:
#   docker compose exec qgis qgis_process list | grep -i "SDU Agro"
#
# Build context: repository root (needs upstream/sdu-agro-tools and upstream/crop-row-connector).
ARG QGIS_IMAGE=qgis/qgis:3.44

# crop-row-connector from the pinned submodule. Its Rust core uses edition 2024, newer than the
# distro rustc, so a throw-away stage builds the wheel with rustup against the SAME interpreter
# QGIS uses (same base image), and only the wheel reaches the final image.
FROM ${QGIS_IMAGE} AS crc-wheel
ENV DEBIAN_FRONTEND=noninteractive PATH=/root/.cargo/bin:${PATH}
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl ca-certificates python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
COPY upstream/crop-row-connector /src/crop-row-connector
RUN python3 -m pip wheel --no-cache-dir --no-deps --wheel-dir /wheels /src/crop-row-connector

FROM ${QGIS_IMAGE}

ENV DEBIAN_FRONTEND=noninteractive \
    QT_QPA_PLATFORM=xcb \
    DISPLAY=:1 \
    HOME=/home/qgis \
    XDG_RUNTIME_DIR=/tmp/runtime-qgis \
    VNC_GEOMETRY=1920x1080

RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb x11vnc x11-utils novnc websockify openbox xterm make \
        python3-pip python3-venv python3-rasterio python3-pandas python3-opencv \
        fonts-dejavu-core procps \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user; QGIS profile lives in the persisted home volume.
# Ubuntu-based images ship an "ubuntu" user on uid 1000; replace it with a named runtime user.
RUN (userdel -r ubuntu 2>/dev/null || true) \
    && useradd --create-home --home-dir /home/qgis --uid 1000 --shell /bin/bash qgis

# Python dependencies of the plugin (upstream/sdu-agro-tools/src/sdu_agro_tools/requirements.txt):
# CDC, crop-row-detector and crop-row-connector. numpy/rasterio/pandas/OpenCV/scipy come from the
# distro so they match the interpreter QGIS was built against (the upstream install guide warns
# that qpip-installed numpy/scipy break QGIS on Ubuntu 24). --no-deps on the three SDU packages
# keeps pip from pulling opencv-python/numpy wheels over the distro builds; their remaining
# dependencies are listed explicitly.
COPY --from=crc-wheel /wheels /tmp/wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-matplotlib python3-scipy python3-skimage python3-shapely \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip install --no-cache-dir --break-system-packages \
         "scikit-learn>=1.7.0" "pybaselines" "icecream" "tqdm" "pyshp" \
    && python3 -m pip install --no-cache-dir --break-system-packages --no-deps \
         "cdc>=1.1.4" "crop-row-detector>=0.3.0" /tmp/wheels/*.whl \
    && python3 -c "import CDC, crop_row_detector, crop_row_connector, numpy; print('agro deps ok, numpy', numpy.__version__)" \
    && rm -rf /tmp/wheels

# The plugin itself, deployed with its own Makefile into a skeleton profile that the entrypoint
# copies into the (persistent) home volume on first start.
COPY upstream/sdu-agro-tools /opt/src/sdu-agro-tools
RUN cd /opt/src/sdu-agro-tools/src/sdu_agro_tools \
    && make deploy HOME=/opt/qgis-skel QGISDIR=.local/share/QGIS/QGIS3/profiles/default/ \
    && mkdir -p /opt/qgis-skel/.local/share/QGIS/QGIS3/profiles/default/QGIS
COPY services/qgis/QGIS3.ini /opt/qgis-skel/.local/share/QGIS/QGIS3/profiles/default/QGIS/QGIS3.ini
COPY services/qgis/entrypoint.sh /usr/local/bin/gs-qgis-entrypoint
RUN chmod 0755 /usr/local/bin/gs-qgis-entrypoint && mkdir -p /data && chown 1000:1000 /data

USER qgis
WORKDIR /data
EXPOSE 6080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('NOVNC_PORT', '6080') + '/vnc.html', timeout=4)"
ENTRYPOINT ["/usr/local/bin/gs-qgis-entrypoint"]
