# mavlink-router (https://github.com/mavlink-router/mavlink-router, Apache-2.0), built from a
# pinned tag. Fans the aircraft's MAVLink out to any number of QGroundControl / MAVSDK clients
# over TCP and writes .tlog flight logs. Config is rendered by gs-init (see compose.yaml).
ARG DEBIAN_IMAGE=debian:trixie-slim

FROM ${DEBIAN_IMAGE} AS build
ARG MAVLINK_ROUTER_REF=v4
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates git g++ meson ninja-build pkg-config python3 \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "${MAVLINK_ROUTER_REF}" --recurse-submodules --shallow-submodules \
        https://github.com/mavlink-router/mavlink-router.git /src
WORKDIR /src
RUN meson setup build . --buildtype=release -Dsystemdsystemunitdir=/usr/lib/systemd/system \
    && ninja -C build \
    && install -D -m 0755 build/src/mavlink-routerd /out/mavlink-routerd

FROM ${DEBIAN_IMAGE}
COPY --from=build /out/mavlink-routerd /usr/local/bin/mavlink-routerd
RUN mkdir -p /logs /etc/mavlink-router
VOLUME ["/logs"]
ENTRYPOINT ["/usr/local/bin/mavlink-routerd"]
CMD ["-c", "/etc/mavlink-router/main.conf"]
