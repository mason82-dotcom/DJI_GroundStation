# Agro API: FastAPI job service around CDC, crop-row-detector and crop-row-connector.
# Build context: repository root (needs upstream/crop-row-connector and services/agro-api).
ARG PYTHON_IMAGE=python:3.13-slim-trixie

# crop-row-connector is built from the pinned submodule. Its Rust core uses edition 2024, so the
# wheel is compiled with a current rustup toolchain in a throw-away stage.
FROM ${PYTHON_IMAGE} AS crc-wheel
ENV PATH=/root/.cargo/bin:${PATH}
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && curl -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable \
    && pip install --no-cache-dir "maturin>=1.4,<2"
COPY upstream/crop-row-connector /src/crop-row-connector
RUN pip wheel --no-cache-dir --no-deps --no-build-isolation --wheel-dir /wheels /src/crop-row-connector

FROM ${PYTHON_IMAGE} AS deps
COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /bin/uv
WORKDIR /build
COPY services/agro-api/pyproject.toml services/agro-api/uv.lock ./
# Everything from the lock except crop-row-connector, which comes from the submodule wheel.
RUN uv export --locked --no-dev --group tools --no-emit-package crop-row-connector --no-hashes \
        --output-file requirements.txt \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
COPY --from=crc-wheel /wheels /wheels
RUN /opt/venv/bin/pip install --no-cache-dir --no-deps /wheels/*.whl

FROM ${PYTHON_IMAGE}
# OpenCV (pulled by crop-row-detector / crop-row-connector) needs these shared libraries.
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home agro \
    && mkdir -p /data && chown 1000:1000 /data
COPY --from=deps /opt/venv /opt/venv
COPY services/agro-api/app /srv/app
ENV PATH=/opt/venv/bin:${PATH} \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/srv \
    AGRO_DATA_ROOT=/data \
    TMPDIR=/data/.tmp
WORKDIR /srv
USER agro
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["sh", "-c", "mkdir -p \"$TMPDIR\" && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'"]
