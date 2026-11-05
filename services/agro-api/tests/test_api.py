import json
import shutil
import time
import zipfile
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.main as main
from app.jobs import JobStore

REPO = Path(__file__).resolve().parents[3]
CRC_DATA = REPO / "upstream" / "crop-row-connector" / "test_dataset" / "input"


def fake_runner(step, cwd, log_path):
    with log_path.open("a") as log:
        log.write(" ".join(step.argv) + "\n")
    (step.out_dir / "result.txt").write_text(step.name)
    return 0


@pytest.fixture
def client(tmp_path, monkeypatch, request):
    runner = getattr(request, "param", fake_runner)
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(main, "DATA_ROOT", data)
    monkeypatch.setattr(main, "JOBS_ROOT", data / "agro-jobs")
    store = JobStore(data / "agro-jobs", runner=runner)
    with TestClient(main.create_app(store)) as c:
        c.data_root = data
        yield c


def wait(client, job_id, timeout=120.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.1)
    raise AssertionError("job did not finish")


def test_health_and_index(client):
    assert client.get("/health").json() == {"status": "ok"}
    assert "Agro-Auswertung" in client.get("/").text
    assert {p["name"] for p in client.get("/api/pipelines").json()} == {
        "cdc",
        "crop-row-detector",
        "crop-row-connector",
        "full",
        "odm",
        "odm-full",
    }


def test_upload_job_runs_and_zips(client):
    files = {"row_information": ("rows.csv", b"a,b\n"), "points_in_rows": ("pts.csv", b"c,d\n")}
    res = client.post(
        "/api/jobs", data={"pipeline": "crop-row-connector", "connector.angle_tolerance": "5"}, files=files
    )
    assert res.status_code == 202, res.text
    job = wait(client, res.json()["id"])
    assert job["status"] == "succeeded"
    assert job["inputs"] == {"row_information": "row_information.csv", "points_in_rows": "points_in_rows.csv"}
    archive = zipfile.ZipFile(BytesIO(client.get(f"/api/jobs/{job['id']}/result.zip").content))
    assert "connected/result.txt" in archive.namelist()
    assert "--angle_tolerance 5" in client.get(f"/api/jobs/{job['id']}/log").text


def test_shared_volume_inputs_and_traversal(client):
    (client.data_root / "fields").mkdir()
    (client.data_root / "fields" / "rows.csv").write_text("x")
    (client.data_root / "fields" / "pts.csv").write_text("y")
    assert {f["path"] for f in client.get("/api/files").json()} == {"fields/rows.csv", "fields/pts.csv"}

    ok = client.post(
        "/api/jobs",
        data={
            "pipeline": "crop-row-connector",
            "row_information_path": "fields/rows.csv",
            "points_in_rows_path": "fields/pts.csv",
        },
    )
    assert ok.status_code == 202, ok.text
    bad = client.post(
        "/api/jobs",
        data={
            "pipeline": "crop-row-connector",
            "row_information_path": "../../etc/passwd",
            "points_in_rows_path": "fields/pts.csv",
        },
    )
    assert bad.status_code == 400
    # a rejected job leaves no directory behind
    assert len(list((client.data_root / "agro-jobs").iterdir())) == 1


def test_bad_requests(client):
    assert client.post("/api/jobs", data={"pipeline": "nope"}).status_code == 400
    assert client.post("/api/jobs", data={"pipeline": "cdc"}).status_code == 400
    assert client.get("/api/jobs/zzz").status_code == 404
    assert client.get("/api/jobs/" + "a" * 32).status_code == 404


def failing_runner(step, cwd, log_path):
    return 3


@pytest.mark.parametrize("client", [failing_runner], indirect=True)
def test_failed_step_is_reported(client):
    files = {"row_information": ("r.csv", b"1"), "points_in_rows": ("p.csv", b"2")}
    job = wait(client, client.post("/api/jobs", data={"pipeline": "crop-row-connector"}, files=files).json()["id"])
    assert job["status"] == "failed" and "exited with 3" in job["error"]
    assert client.get(f"/api/jobs/{job['id']}/result.zip").status_code == 409


def test_restart_marks_running_jobs_interrupted(tmp_path):
    store = JobStore(tmp_path)
    job_id, _ = store.new_job_dir()
    (tmp_path / job_id / "job.json").write_text(
        json.dumps({"id": job_id, "pipeline": "cdc", "status": "running", "params": {}, "inputs": {}, "created": 1})
    )
    assert JobStore(tmp_path).get(job_id).status == "failed"


@pytest.mark.skipif(shutil.which("crop-row-connector") is None or not CRC_DATA.is_dir(), reason="tool not installed")
@pytest.mark.parametrize("client", [None], indirect=True)
def test_real_crop_row_connector_on_upstream_test_dataset(client, request):
    """End to end with the real CLI and the dataset shipped in upstream/crop-row-connector."""
    from app.jobs import subprocess_runner

    client.app.state.store._runner = subprocess_runner
    files = {
        "row_information": ("row_information_global.csv", (CRC_DATA / "row_information_global.csv").read_bytes()),
        "points_in_rows": ("points_in_rows.csv", (CRC_DATA / "points_in_rows.csv").read_bytes()),
    }
    data = {
        "pipeline": "crop-row-connector",
        "connector.distance_tolerance": "0.12",
        "connector.angle_tolerance": "6.9",
    }
    job = wait(client, client.post("/api/jobs", data=data, files=files).json()["id"], timeout=600)
    log = client.get(f"/api/jobs/{job['id']}/log").text
    assert job["status"] == "succeeded", log
    names = zipfile.ZipFile(BytesIO(client.get(f"/api/jobs/{job['id']}/result.zip").content)).namelist()
    assert "connected/connected_crop_rows.csv" in names
    assert any(n.startswith("connected/healthy") for n in names)


def test_odm_job_from_shared_folder(client):
    folder = client.data_root / "media" / "mini3"
    folder.mkdir(parents=True)
    for i in range(6):
        (folder / f"DJI_{i}.JPG").write_bytes(b"x")
    assert client.get("/api/folders").json() == [{"path": "media/mini3", "images": 6}]
    res = client.post("/api/jobs", data={"pipeline": "odm", "images_dir_path": "media/mini3"})
    assert res.status_code == 202, res.text
    assert wait(client, res.json()["id"])["status"] == "succeeded"
    # a file is not accepted where a folder is expected
    bad = client.post("/api/jobs", data={"pipeline": "odm", "images_dir_path": "media/mini3/DJI_0.JPG"})
    assert bad.status_code == 400
