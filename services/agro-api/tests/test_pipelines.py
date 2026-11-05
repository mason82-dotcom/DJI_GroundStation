from pathlib import Path

import pytest

from app.pipelines import PipelineError, build_steps

WORK = Path("/w")
FULL_INPUTS = {"orthomosaic": Path("/d/o.tif"), "reference": Path("/d/r.png"), "annotated": Path("/d/a.png")}


def test_full_pipeline_chains_documented_outputs():
    steps = build_steps("full", FULL_INPUTS, WORK, {"detector.tile_size": "500", "connector.angle_tolerance": "6.9"})
    assert [s.name for s in steps] == ["cdc", "crop-row-detector", "crop-row-connector"]
    assert steps[0].argv[:4] == ["CDC", "/d/o.tif", "/d/r.png", "/d/a.png"]
    # detector reads CDC's segmented output and plots on the original orthomosaic
    assert steps[1].argv[1] == "/w/cdc/orthomosaic.tiff"
    assert ["--orthomosaic", "/d/o.tif"] == steps[1].argv[5:7]
    assert ["--tile_size", "500"] == steps[1].argv[-2:]
    # connector reads the detector's two CSV files
    assert steps[2].argv[1:3] == ["/w/crop-rows/row_information_global.csv", "/w/crop-rows/points_in_rows.csv"]
    assert steps[2].argv[-2:] == ["--angle_tolerance", "6.9"]
    assert steps[2].out_dir == WORK / "connected"


def test_missing_input_is_rejected():
    with pytest.raises(PipelineError, match="annotated"):
        build_steps("cdc", {"orthomosaic": Path("o"), "reference": Path("r")}, WORK, {})


@pytest.mark.parametrize(
    "params",
    [
        {"connector.angle_tolerance": "1; rm -rf /"},
        {"connector.angle_tolerance": "nan"},
        {"connector.unknown": "1"},
        {"cdc.method": "kmeans"},
        {"cdc.tile_size": "-5"},
    ],
)
def test_bad_parameters_are_rejected(params):
    kind = "full" if params and next(iter(params)).startswith("cdc") else "crop-row-connector"
    inputs = FULL_INPUTS if kind == "full" else {"row_information": Path("a"), "points_in_rows": Path("b")}
    with pytest.raises(PipelineError):
        build_steps(kind, inputs, WORK, params)


def test_empty_form_values_use_tool_defaults():
    steps = build_steps(
        "crop-row-connector",
        {"row_information": Path("a"), "points_in_rows": Path("b")},
        WORK,
        {"connector.angle_tolerance": ""},
    )
    assert "--angle_tolerance" not in steps[0].argv


def test_unknown_pipeline():
    with pytest.raises(PipelineError, match="unknown pipeline"):
        build_steps("nope", {}, WORK, {})
