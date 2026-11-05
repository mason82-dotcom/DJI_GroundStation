from pathlib import Path

import pytest

from app import odm_client
from app.pipelines import PipelineError, build_steps


class FakeOdm:
    def __init__(self, codes):
        self.codes = list(codes)
        self.created = None

    def create(self, name, options, images):
        self.created = (name, options, [p.name for p in images])
        return "uuid-1"

    def info(self, uuid):
        return {"status": {"code": self.codes.pop(0)}, "progress": 50}

    def download(self, uuid, asset, target):
        assert asset == "orthophoto.tif"
        target.write_bytes(b"GEOTIFF")


def make_images(folder: Path, count=6):
    folder.mkdir(parents=True)
    for i in range(count):
        (folder / f"DJI_{i:04d}.JPG").write_bytes(b"x")
    (folder / "notes.txt").write_text("ignored")
    return folder


def test_odm_client_runs_task_and_publishes(tmp_path):
    images = make_images(tmp_path / "imgs")
    args = odm_client.parse_args(
        [str(images), "--out", str(tmp_path / "out"), "--publish", str(tmp_path / "pub" / "o.tif"), "--fast-orthophoto"]
    )
    fake = FakeOdm([20, 20, 40])
    assert odm_client.run(args, odm=fake, sleep=lambda s: None) == 0
    assert len(fake.created[2]) == 6
    assert {"name": "fast-orthophoto", "value": True} in fake.created[1]
    assert (tmp_path / "out" / "odm_orthophoto.tif").read_bytes() == b"GEOTIFF"
    assert (tmp_path / "pub" / "o.tif").read_bytes() == b"GEOTIFF"


def test_odm_client_reports_failed_task(tmp_path):
    args = odm_client.parse_args([str(make_images(tmp_path / "imgs")), "--out", str(tmp_path / "out")])
    assert odm_client.run(args, odm=FakeOdm([10, 30]), sleep=lambda s: None) == 1


def test_odm_client_needs_enough_images(tmp_path):
    args = odm_client.parse_args([str(make_images(tmp_path / "imgs", count=2)), "--out", str(tmp_path / "o")])
    assert odm_client.run(args, odm=FakeOdm([]), sleep=lambda s: None) == 2


def test_odm_full_pipeline_feeds_orthophoto_into_cdc(tmp_path):
    inputs = {"images_dir": Path("/d/imgs"), "reference": Path("/d/r.png"), "annotated": Path("/d/a.png")}
    steps = build_steps(
        "odm-full",
        inputs,
        Path("/w"),
        {"odm.fast_orthophoto": "true", "odm.dsm": "false", "odm.orthophoto_resolution": "3"},
        job_name="odm-abc",
        publish_dir=Path("/data/orthomosaics"),
    )
    assert [s.name for s in steps] == ["odm", "cdc", "crop-row-detector", "crop-row-connector"]
    odm = steps[0].argv
    assert odm[1:3] == ["-m", "app.odm_client"] and "--fast-orthophoto" in odm and "--dsm" not in odm
    assert odm[odm.index("--publish") + 1] == "/data/orthomosaics/odm-abc.tif"
    assert steps[1].argv[1] == "/w/odm/odm_orthophoto.tif"


def test_odm_switch_validation():
    with pytest.raises(PipelineError):
        build_steps("odm", {"images_dir": Path("/i")}, Path("/w"), {"odm.dsm": "yes please"})
