"""Job store and runner for agricultural processing jobs.

Each job lives in its own directory under ``<jobs_root>/<job_id>/``::

    job.json      status, pipeline, parameters, timestamps, step results
    inputs/       uploaded files (or nothing, when inputs reference the shared /data volume)
    output/       everything the tools write
    log.txt       combined stdout/stderr of every step

State is kept on disk only, so the API can restart without losing finished results; a job
that was running when the process died is marked ``failed`` (``interrupted``) on start-up.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
import zipfile
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .pipelines import Step, build_steps

QUEUED, RUNNING, SUCCEEDED, FAILED = "queued", "running", "succeeded", "failed"

Runner = Callable[[Step, Path, Path], int]


def subprocess_runner(step: Step, cwd: Path, log_path: Path) -> int:
    """Run one step without a shell, appending its output to the job log."""
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {' '.join(step.argv)}\n")
        log.flush()
        completed = subprocess.run(  # noqa: S603 - argv list built from a whitelist, no shell
            step.argv, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=False
        )
    return completed.returncode


@dataclass
class Job:
    id: str
    pipeline: str
    status: str
    params: dict[str, str]
    inputs: dict[str, str]
    created: float
    started: float | None = None
    finished: float | None = None
    error: str | None = None
    steps: list[dict[str, object]] = field(default_factory=list)

    def public(self) -> dict[str, object]:
        data = asdict(self)
        # Inputs are shown by file name only; the absolute layout of the volume is not API.
        data["inputs"] = {name: Path(path).name for name, path in self.inputs.items()}
        return data


class JobStore:
    def __init__(
        self,
        root: Path,
        runner: Runner = subprocess_runner,
        max_parallel: int = 1,
        publish_dir: Path | None = None,
    ):
        self.root = root
        self.publish_dir = publish_dir
        self.root.mkdir(parents=True, exist_ok=True)
        self._runner = runner
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max(1, max_parallel), thread_name_prefix="agro-job")
        self._recover()

    # -- persistence -------------------------------------------------------------------------
    def job_dir(self, job_id: str) -> Path:
        # job ids are server-generated hex; reject anything else before touching the disk.
        if not job_id or any(c not in "0123456789abcdef" for c in job_id):
            raise KeyError(job_id)
        return self.root / job_id

    def _save(self, job: Job) -> None:
        path = self.job_dir(job.id) / "job.json"
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(job), indent=2))
        os.replace(tmp, path)

    def get(self, job_id: str) -> Job:
        path = self.job_dir(job_id) / "job.json"
        if not path.is_file():
            raise KeyError(job_id)
        return Job(**json.loads(path.read_text()))

    def list(self) -> list[Job]:
        jobs = []
        for path in self.root.glob("*/job.json"):
            try:
                jobs.append(Job(**json.loads(path.read_text())))
            except (OSError, ValueError, TypeError):
                continue
        return sorted(jobs, key=lambda job: job.created, reverse=True)

    def _recover(self) -> None:
        for job in self.list():
            if job.status in (QUEUED, RUNNING):
                job.status, job.error, job.finished = FAILED, "interrupted (service restarted)", time.time()
                self._save(job)

    # -- lifecycle ---------------------------------------------------------------------------
    def new_job_dir(self) -> tuple[str, Path]:
        job_id = uuid.uuid4().hex
        job_dir = self.root / job_id
        (job_dir / "inputs").mkdir(parents=True)
        (job_dir / "output").mkdir()
        return job_id, job_dir

    def submit(self, job_id: str, pipeline: str, inputs: Mapping[str, Path], params: Mapping[str, str]) -> Job:
        """Validate and queue a job whose inputs already sit in place. Raises PipelineError."""
        job_dir = self.job_dir(job_id)
        steps = build_steps(  # validates first
            pipeline, inputs, job_dir / "output", params, job_name=f"odm-{job_id[:8]}", publish_dir=self.publish_dir
        )
        job = Job(
            id=job_id,
            pipeline=pipeline,
            status=QUEUED,
            params={k: str(v) for k, v in params.items() if str(v).strip()},
            inputs={k: str(v) for k, v in inputs.items()},
            created=time.time(),
        )
        self._save(job)
        self._pool.submit(self._run, job, steps)
        return job

    def _run(self, job: Job, steps: list[Step]) -> None:
        job_dir = self.job_dir(job.id)
        log_path = job_dir / "log.txt"
        job.status, job.started = RUNNING, time.time()
        self._save(job)
        try:
            for step in steps:
                started = time.time()
                step.out_dir.mkdir(parents=True, exist_ok=True)
                code = self._runner(step, job_dir, log_path)
                job.steps.append({"name": step.name, "returncode": code, "seconds": round(time.time() - started, 1)})
                self._save(job)
                if code != 0:
                    job.status, job.error = FAILED, f"step {step.name} exited with {code} (see log)"
                    break
            else:
                job.status = SUCCEEDED
        except Exception as error:  # noqa: BLE001 - a job must never take the worker thread down
            job.status, job.error = FAILED, f"{type(error).__name__}: {error}"
        job.finished = time.time()
        self._save(job)

    def delete(self, job_id: str) -> None:
        job = self.get(job_id)
        if job.status in (QUEUED, RUNNING):
            raise RuntimeError("job is still active")
        shutil.rmtree(self.job_dir(job_id))

    def result_zip(self, job_id: str) -> Path:
        job = self.get(job_id)
        if job.status != SUCCEEDED:
            raise RuntimeError(f"job is {job.status}")
        job_dir = self.job_dir(job_id)
        archive = job_dir / "result.zip"
        if not archive.exists():
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for path in sorted((job_dir / "output").rglob("*")):
                    if path.is_file():
                        zf.write(path, path.relative_to(job_dir / "output"))
                if (job_dir / "log.txt").exists():
                    zf.write(job_dir / "log.txt", "log.txt")
        return archive

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
