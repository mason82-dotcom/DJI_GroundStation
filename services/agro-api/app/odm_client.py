"""Build an orthomosaic from a folder of drone photos with NodeODM (OpenDroneMap).

Used as one pipeline step by the Agro API (``python -m app.odm_client ...``), so it runs through
the same argv/log runner as the SDU tools. It uploads images one request at a time through
NodeODM's chunked API (``/task/new/init`` -> ``/task/new/upload`` -> ``/task/new/commit``), so
hundreds of full-size photos never have to fit in a single request, then polls the task and
downloads ``orthophoto.tif``.

NodeODM API: https://github.com/OpenDroneMap/NodeODM/blob/master/docs/index.adoc
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

import httpx

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".tif", ".tiff", ".png", ".dng"}
STATUS = {10: "queued", 20: "running", 30: "failed", 40: "completed", 50: "canceled"}


def find_images(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)


def odm_options(args: argparse.Namespace) -> list[dict[str, object]]:
    options: list[dict[str, object]] = [{"name": "orthophoto-resolution", "value": args.orthophoto_resolution}]
    if args.feature_quality:
        options.append({"name": "feature-quality", "value": args.feature_quality})
    if args.fast_orthophoto:
        options.append({"name": "fast-orthophoto", "value": True})
    if args.dsm:
        options.append({"name": "dsm", "value": True})
    return options


class NodeOdm:
    def __init__(self, url: str, token: str = "", timeout: float = 600.0):
        self._client = httpx.Client(base_url=url.rstrip("/"), timeout=timeout)
        self._params = {"token": token} if token else {}

    def _json(self, response: httpx.Response) -> dict:
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("error"):
            raise RuntimeError(f"NodeODM: {data['error']}")
        return data

    def create(self, name: str, options: list[dict[str, object]], images: list[Path]) -> str:
        init = self._json(
            self._client.post(
                "/task/new/init", params=self._params, data={"name": name, "options": json.dumps(options)}
            )
        )
        uuid = init["uuid"]
        for count, image in enumerate(images, 1):
            with image.open("rb") as fh:
                self._json(
                    self._client.post(
                        f"/task/new/upload/{uuid}", params=self._params, files={"images": (image.name, fh)}
                    )
                )
            if count % 25 == 0 or count == len(images):
                print(f"uploaded {count}/{len(images)} images", flush=True)
        self._json(self._client.post(f"/task/new/commit/{uuid}", params=self._params))
        return uuid

    def info(self, uuid: str) -> dict:
        return self._json(self._client.get(f"/task/{uuid}/info", params=self._params))

    def download(self, uuid: str, asset: str, target: Path) -> None:
        with self._client.stream("GET", f"/task/{uuid}/download/{asset}", params=self._params) as response:
            response.raise_for_status()
            partial = target.with_name(target.name + ".part")
            with partial.open("wb") as out:
                for chunk in response.iter_bytes(1024 * 1024):
                    out.write(chunk)
            os.replace(partial, target)


def run(args: argparse.Namespace, odm: NodeOdm | None = None, sleep=time.sleep) -> int:
    images = find_images(args.images_dir)
    if len(images) < 5:
        print(f"need at least 5 images in {args.images_dir}, found {len(images)}", file=sys.stderr)
        return 2
    odm = odm or NodeOdm(args.url, args.token)
    args.out.mkdir(parents=True, exist_ok=True)
    uuid = odm.create(args.name, odm_options(args), images)
    print(f"NodeODM task {uuid} created with {len(images)} images", flush=True)
    last = None
    while True:
        info = odm.info(uuid)
        code = (info.get("status") or {}).get("code")
        progress = info.get("progress")
        if (code, progress) != last:
            print(f"status={STATUS.get(code, code)} progress={progress}", flush=True)
            last = (code, progress)
        if code == 40:
            break
        if code in (30, 50):
            print(f"NodeODM task ended: {info.get('status')}", file=sys.stderr)
            return 1
        sleep(args.poll_seconds)
    target = args.out / "odm_orthophoto.tif"
    odm.download(uuid, "orthophoto.tif", target)
    print(f"orthophoto saved to {target} ({target.stat().st_size} bytes)", flush=True)
    if args.publish:
        args.publish.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(target, args.publish)
        print(f"published to shared volume: {args.publish}", flush=True)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("images_dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--name", default="groundstation")
    parser.add_argument("--url", default=os.environ.get("NODEODM_URL", "http://nodeodm:3000"))
    parser.add_argument("--token", default=os.environ.get("NODEODM_TOKEN", ""))
    parser.add_argument("--publish", type=Path, help="also copy the orthophoto to this path")
    parser.add_argument("--orthophoto-resolution", type=float, default=2.0, help="cm/pixel")
    parser.add_argument("--feature-quality", choices=("ultra", "high", "medium", "low", "lowest"))
    parser.add_argument("--fast-orthophoto", action="store_true")
    parser.add_argument("--dsm", action="store_true")
    parser.add_argument("--poll-seconds", type=float, default=10.0)
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.exit(run(parse_args(sys.argv[1:])))
