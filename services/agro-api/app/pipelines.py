"""Command lines for the SDU agricultural tool chain.

The three SDU UAS Center tools are command-line programs:

* ``CDC`` (color-based distance) turns an orthomosaic plus an annotated reference image into a
  segmented orthomosaic (``<out>/orthomosaic.tiff``).
* ``crop-row-detector`` finds crop rows tile by tile in that segmented orthomosaic and writes
  ``row_information_global.csv`` and ``points_in_rows.csv``.
* ``crop-row-connector`` (upstream/crop-row-connector) joins the row fragments across tile
  borders and classifies vegetation along each row as healthy or unhealthy.

This module only *builds* argv lists; :mod:`app.jobs` runs them. Every user-supplied value is
validated against a whitelist and passed as a separate argv element (never through a shell).
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path


class PipelineError(ValueError):
    """Invalid pipeline request (unknown kind, missing input, bad parameter)."""


@dataclass(frozen=True)
class Param:
    """A whitelisted CLI option: form key -> ``--flag`` with a type check."""

    flag: str
    parse: Callable[[str], object]
    choices: tuple[str, ...] = ()
    #: A switch without a value (``--fast-orthophoto``): "true"/"1"/"on" sets it, "false" omits it.
    switch: bool = False

    def render(self, key: str, raw: str) -> list[str]:
        raw = raw.strip()
        if self.switch:
            if raw.lower() not in ("true", "false", "1", "0", "on", "off"):
                raise PipelineError(f"{key} must be true or false")
            return [self.flag] if raw.lower() in ("true", "1", "on") else []
        if self.choices and raw not in self.choices:
            raise PipelineError(f"{key} must be one of {', '.join(self.choices)}")
        try:
            value = self.parse(raw)
        except ValueError as error:
            raise PipelineError(f"{key}: {error}") from error
        return [self.flag, str(value)]


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise ValueError("must be a positive integer")
    return value


def _float(raw: str) -> float:
    value = float(raw)
    if value != value or value in (float("inf"), float("-inf")):  # NaN / inf
        raise ValueError("must be a finite number")
    return value


CDC_PARAMS: dict[str, Param] = {
    "method": Param("--method", str, ("mahalanobis", "gmm")),
    "param": Param("--param", _positive_int),
    "scale": Param("--scale", _float),
    "tile_size": Param("--tile_size", _positive_int),
}
DETECTOR_PARAMS: dict[str, Param] = {
    "segmentation_threshold": Param("--segmentation_threshold", _float),
    "vegetation_threshold": Param("--vegetation_threshold", _float),
    "tile_size": Param("--tile_size", _positive_int),
    "expected_crop_row_distance": Param("--expected_crop_row_distance", _float),
    "min_angle": Param("--min_angle", _float),
    "max_angle": Param("--max_angle", _float),
    "angle_resolution": Param("--angle_resolution", _positive_int),
}
CONNECTOR_PARAMS: dict[str, Param] = {
    "angle_tolerance": Param("--angle_tolerance", _float),
    "distance_tolerance": Param("--distance_tolerance", _float),
    "vegetation_threshold": Param("--vegetation_threshold", _float),
    "min_unhealthy_vegetation_length": Param("--min_unhealthy_vegetation_length", _float),
    "max_segment_length": Param("--max_segment_length", _float),
}
ODM_PARAMS: dict[str, Param] = {
    "orthophoto_resolution": Param("--orthophoto-resolution", _float),
    "feature_quality": Param("--feature-quality", str, ("ultra", "high", "medium", "low", "lowest")),
    "fast_orthophoto": Param("--fast-orthophoto", str, switch=True),
    "dsm": Param("--dsm", str, switch=True),
}


@dataclass(frozen=True)
class Step:
    name: str
    argv: list[str]
    out_dir: Path


@dataclass(frozen=True)
class PipelineKind:
    name: str
    description: str
    inputs: tuple[str, ...]
    optional_inputs: tuple[str, ...] = ()
    # Parameter groups this pipeline accepts, keyed by prefix ("cdc.", "detector.", ...).
    param_groups: tuple[str, ...] = field(default_factory=tuple)


PIPELINES: dict[str, PipelineKind] = {
    "cdc": PipelineKind(
        "cdc",
        "Color-based segmentation of an orthomosaic (CDC).",
        ("orthomosaic", "reference", "annotated"),
        param_groups=("cdc",),
    ),
    "crop-row-detector": PipelineKind(
        "crop-row-detector",
        "Detect crop rows in a segmented orthomosaic.",
        ("segmented_orthomosaic",),
        optional_inputs=("orthomosaic",),
        param_groups=("detector",),
    ),
    "crop-row-connector": PipelineKind(
        "crop-row-connector",
        "Connect tiled crop-row fragments and classify vegetation health.",
        ("row_information", "points_in_rows"),
        param_groups=("connector",),
    ),
    "full": PipelineKind(
        "full",
        "Orthomosaic -> CDC -> crop-row-detector -> crop-row-connector.",
        ("orthomosaic", "reference", "annotated"),
        param_groups=("cdc", "detector", "connector"),
    ),
    "odm": PipelineKind(
        "odm",
        "Drone photos (folder) -> orthomosaic with NodeODM / OpenDroneMap.",
        ("images_dir",),
        param_groups=("odm",),
    ),
    "odm-full": PipelineKind(
        "odm-full",
        "Drone photos -> NodeODM orthomosaic -> CDC -> crop-row-detector -> crop-row-connector.",
        ("images_dir", "reference", "annotated"),
        param_groups=("odm", "cdc", "detector", "connector"),
    ),
}

_GROUP_PARAMS = {"cdc": CDC_PARAMS, "detector": DETECTOR_PARAMS, "connector": CONNECTOR_PARAMS, "odm": ODM_PARAMS}


def is_dir_input(name: str) -> bool:
    """Inputs named ``*_dir`` are folders on the shared volume, not single files."""
    return name.endswith("_dir")


def split_params(kind: PipelineKind, params: Mapping[str, str]) -> dict[str, list[str]]:
    """Validate ``group.key`` parameters and render them as CLI flags per group.

    Empty values are ignored (an untouched HTML form field). Unknown keys are an error so a
    typo does not silently run with the tool's default.
    """
    rendered: dict[str, list[str]] = {group: [] for group in kind.param_groups}
    for full_key, raw in params.items():
        if raw is None or str(raw).strip() == "":
            continue
        group, _, key = full_key.partition(".")
        if group not in rendered or key not in _GROUP_PARAMS[group]:
            raise PipelineError(f"unknown parameter {full_key!r} for pipeline {kind.name!r}")
        rendered[group] += _GROUP_PARAMS[group][key].render(full_key, str(raw))
    return rendered


def cdc_step(orthomosaic: Path, reference: Path, annotated: Path, out: Path, flags: list[str]) -> Step:
    return Step(
        "cdc",
        ["CDC", str(orthomosaic), str(reference), str(annotated), "--output_location", str(out), *flags],
        out,
    )


def detector_step(segmented: Path, out: Path, flags: list[str], orthomosaic: Path | None = None) -> Step:
    argv = ["crop-row-detector", str(segmented), "--output_location", str(out), "--overwrite"]
    if orthomosaic is not None:
        argv += ["--orthomosaic", str(orthomosaic)]
    return Step("crop-row-detector", argv + flags, out)


def odm_step(images_dir: Path, out: Path, flags: list[str], name: str, publish: Path | None) -> Step:
    argv = [sys.executable, "-m", "app.odm_client", str(images_dir), "--out", str(out), "--name", name]
    if publish is not None:
        argv += ["--publish", str(publish)]
    return Step("odm", argv + flags, out)


def connector_step(rows: Path, points: Path, out: Path, flags: list[str]) -> Step:
    return Step(
        "crop-row-connector",
        [
            "crop-row-connector",
            str(rows),
            str(points),
            "--output_path_connected_crop_rows",
            str(out / "connected_crop_rows.csv"),
            "--output_path_vegetation_points",
            str(out / "line_points.csv"),
            "--output_path_healthy_vegetation_segments",
            str(out / "healthy"),
            "--output_path_unhealthy_vegetation_segments",
            str(out / "unhealthy"),
            *flags,
        ],
        out,
    )


def build_steps(
    kind_name: str,
    inputs: Mapping[str, Path],
    work: Path,
    params: Mapping[str, str],
    *,
    job_name: str = "groundstation",
    publish_dir: Path | None = None,
) -> list[Step]:
    """Return the ordered steps for one job.

    ``work`` is the job's output directory. ``publish_dir`` (the shared volume's
    ``orthomosaics/`` folder) also receives a copy of an ODM orthophoto, so later jobs and the
    QGIS desktop can pick it without downloading the job result.
    """
    kind = PIPELINES.get(kind_name)
    if kind is None:
        raise PipelineError(f"unknown pipeline {kind_name!r}; choose one of {', '.join(PIPELINES)}")
    missing = [name for name in kind.inputs if name not in inputs]
    if missing:
        raise PipelineError(f"pipeline {kind_name!r} needs input(s): {', '.join(missing)}")
    flags = split_params(kind, params)

    if kind_name == "cdc":
        return [cdc_step(inputs["orthomosaic"], inputs["reference"], inputs["annotated"], work / "cdc", flags["cdc"])]
    if kind_name == "crop-row-detector":
        return [
            detector_step(
                inputs["segmented_orthomosaic"], work / "crop-rows", flags["detector"], inputs.get("orthomosaic")
            )
        ]
    if kind_name == "crop-row-connector":
        return [
            connector_step(inputs["row_information"], inputs["points_in_rows"], work / "connected", flags["connector"])
        ]

    steps: list[Step] = []
    orthomosaic = inputs.get("orthomosaic")
    if kind_name in ("odm", "odm-full"):
        odm_out = work / "odm"
        publish = publish_dir / f"{job_name}.tif" if publish_dir is not None else None
        steps.append(odm_step(inputs["images_dir"], odm_out, flags["odm"], job_name, publish))
        if kind_name == "odm":
            return steps
        orthomosaic = odm_out / "odm_orthophoto.tif"
    assert orthomosaic is not None

    # full pipeline: each step reads the previous step's documented output files.
    cdc_out, rows_out, connected_out = work / "cdc", work / "crop-rows", work / "connected"
    return steps + [
        cdc_step(orthomosaic, inputs["reference"], inputs["annotated"], cdc_out, flags["cdc"]),
        detector_step(cdc_out / "orthomosaic.tiff", rows_out, flags["detector"], orthomosaic),
        connector_step(
            rows_out / "row_information_global.csv",
            rows_out / "points_in_rows.csv",
            connected_out,
            flags["connector"],
        ),
    ]
