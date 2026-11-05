"""Agro API: HTTP front end for the SDU agricultural tool chain.

Runs CDC, crop-row-detector and crop-row-connector (see :mod:`app.pipelines`) as background
jobs. Inputs are either uploaded with the request or picked from the shared ``/data`` volume
that the QGIS web desktop and the other services also mount, so a large orthomosaic only has
to reach the ground station once.

Authentication is done by the Caddy proxy in front of this service; the container port is only
published on the host's loopback interface.
"""

from __future__ import annotations

import os
import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from starlette.datastructures import UploadFile

from .jobs import JobStore
from .odm_client import IMAGE_SUFFIXES
from .pipelines import PIPELINES, PipelineError, is_dir_input

DATA_ROOT = Path(os.environ.get("AGRO_DATA_ROOT", "/data")).resolve()
PUBLISH_DIR = Path(os.environ.get("AGRO_PUBLISH_DIR", str(DATA_ROOT / "orthomosaics"))).resolve()
JOBS_ROOT = Path(os.environ.get("AGRO_JOBS_ROOT", str(DATA_ROOT / "agro-jobs"))).resolve()
MAX_UPLOAD_BYTES = int(float(os.environ.get("AGRO_MAX_UPLOAD_MB", "20480")) * 1024 * 1024)
MAX_PARALLEL = int(os.environ.get("AGRO_MAX_PARALLEL_JOBS", "1"))
STATIC_DIR = Path(__file__).parent / "static"
_SUFFIX = re.compile(r"^\.[A-Za-z0-9]{1,10}$")


def create_app(store: JobStore | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.store = store or JobStore(JOBS_ROOT, max_parallel=MAX_PARALLEL, publish_dir=PUBLISH_DIR)
        yield
        app.state.store.shutdown()

    app = FastAPI(title="DJI GroundStation Agro API", version="1.0.0", lifespan=lifespan)

    def jobs(request: Request) -> JobStore:
        return request.app.state.store

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/pipelines")
    def pipelines() -> list[dict[str, object]]:
        return [
            {
                "name": kind.name,
                "description": kind.description,
                "inputs": list(kind.inputs),
                "optionalInputs": list(kind.optional_inputs),
                "paramGroups": list(kind.param_groups),
            }
            for kind in PIPELINES.values()
        ]

    @app.get("/api/files")
    def files() -> list[dict[str, object]]:
        """Files on the shared data volume that can be used as job inputs."""
        result = []
        for path in sorted(DATA_ROOT.rglob("*")):
            if not path.is_file() or JOBS_ROOT in path.parents or any(p.startswith(".") for p in path.parts):
                continue
            result.append({"path": str(path.relative_to(DATA_ROOT)), "bytes": path.stat().st_size})
        return result

    @app.get("/api/folders")
    def folders() -> list[dict[str, object]]:
        """Folders on the shared volume that contain images (ODM input candidates)."""
        result = []
        for path in sorted(p for p in DATA_ROOT.rglob("*") if p.is_dir()):
            if path == JOBS_ROOT or JOBS_ROOT in path.parents or any(p.startswith(".") for p in path.parts):
                continue
            count = sum(1 for f in path.iterdir() if f.suffix.lower() in IMAGE_SUFFIXES)
            if count:
                result.append({"path": str(path.relative_to(DATA_ROOT)), "images": count})
        return result

    @app.post("/api/jobs", status_code=202)
    async def create_job(request: Request) -> JSONResponse:
        form = await request.form()
        pipeline = str(form.get("pipeline", "")).strip()
        kind = PIPELINES.get(pipeline)
        if kind is None:
            raise HTTPException(400, f"unknown pipeline {pipeline!r}; choose one of {', '.join(PIPELINES)}")

        store = jobs(request)
        job_id, job_dir = store.new_job_dir()
        try:
            inputs: dict[str, Path] = {}
            for name in kind.inputs + kind.optional_inputs:
                upload = form.get(name)
                shared = str(form.get(f"{name}_path", "") or "").strip()
                if isinstance(upload, UploadFile) and upload.filename:
                    inputs[name] = await _save_upload(upload, job_dir / "inputs", name)
                elif shared:
                    inputs[name] = _shared_path(shared, directory=is_dir_input(name))
            params = {
                key: str(value) for key, value in form.items() if "." in key and not isinstance(value, UploadFile)
            }
            job = store.submit(job_id, pipeline, inputs, params)
        except (PipelineError, ValueError) as error:
            shutil.rmtree(job_dir, ignore_errors=True)
            raise HTTPException(400, str(error)) from error
        return JSONResponse(job.public(), status_code=202)

    @app.get("/api/jobs")
    def list_jobs(request: Request) -> list[dict[str, object]]:
        return [job.public() for job in jobs(request).list()]

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, request: Request) -> dict[str, object]:
        return _job_or_404(jobs(request), job_id).public()

    @app.get("/api/jobs/{job_id}/log", response_class=PlainTextResponse)
    def get_log(job_id: str, request: Request) -> str:
        store = jobs(request)
        _job_or_404(store, job_id)
        log = store.job_dir(job_id) / "log.txt"
        return log.read_text(errors="replace") if log.exists() else ""

    @app.get("/api/jobs/{job_id}/result.zip")
    def get_result(job_id: str, request: Request) -> FileResponse:
        store = jobs(request)
        _job_or_404(store, job_id)
        try:
            archive = store.result_zip(job_id)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error
        return FileResponse(archive, media_type="application/zip", filename=f"agro-{job_id[:8]}.zip")

    @app.delete("/api/jobs/{job_id}", status_code=204)
    def delete_job(job_id: str, request: Request) -> None:
        store = jobs(request)
        _job_or_404(store, job_id)
        try:
            store.delete(job_id)
        except RuntimeError as error:
            raise HTTPException(409, str(error)) from error

    return app


def _job_or_404(store: JobStore, job_id: str):
    try:
        return store.get(job_id)
    except KeyError as error:
        raise HTTPException(404, "job not found") from error


def _shared_path(relative: str, directory: bool = False) -> Path:
    """Resolve a path on the shared volume, refusing anything outside it."""
    candidate = (DATA_ROOT / relative).resolve()
    exists = candidate.is_dir() if directory else candidate.is_file()
    if DATA_ROOT not in candidate.parents or not exists:
        kind = "folder" if directory else "file"
        raise ValueError(f"{relative!r} is not a {kind} on the shared data volume")
    return candidate


async def _save_upload(upload: UploadFile, target_dir: Path, name: str) -> Path:
    suffix = Path(upload.filename or "").suffix
    target = target_dir / (name + (suffix if _SUFFIX.match(suffix) else ""))
    written = 0
    with target.open("wb") as out:
        while chunk := await upload.read(1024 * 1024):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                raise ValueError(f"upload {name!r} exceeds AGRO_MAX_UPLOAD_MB")
            out.write(chunk)
    return target


app = create_app()
