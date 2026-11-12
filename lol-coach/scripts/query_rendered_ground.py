"""Query native spectator shading using paired, registered top-down captures."""
import argparse
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lol_coach.ngrid import parse_ngrid


def load_pair(manifest_path, at):
    m = json.loads(manifest_path.read_bytes())
    if m.get("schema") != "native-replay-fog-pairs/v1":
        raise ValueError("Unsupported native capture manifest")
    images, refs = {}, {}
    for r in m["frames"]:
        settings = r["render"]
        if abs(r["capture_start"]-at) > .002 or settings["interfaceAll"]:
            continue
        playback = r["playback_before_recording"]
        if not playback["paused"] or playback["seeking"] or abs(playback["time"]-at) > .002:
            raise ValueError("Capture time is not bound to a paused replay tick")
        path = (manifest_path.parent/r["file"]).resolve()
        if not path.is_relative_to(manifest_path.parent.resolve()):
            raise ValueError("Capture lies outside the manifest directory")
        data = path.read_bytes()
        if sha256(data).hexdigest() != r["sha256"]:
            raise ValueError("Changed native image")
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        key = settings["fogOfWar"]
        if key in images or image is None or image.shape[:2] != (r["height"], r["width"]):
            raise ValueError("Ambiguous or invalid native capture")
        images[key], refs[key] = image, r
    if set(images) != {True, False} or images[True].shape != images[False].shape:
        raise ValueError("Need a time-matched fog-on and fog-off pair")
    on, off = (refs[k]["render"] for k in (True, False))
    keys = ("cameraPosition", "cameraRotation", "cameraMode", "fieldOfView", "champions", "minions", "particles")
    if (any(on[k] != off[k] for k in keys) or on["cameraMode"] != "fps" or any(on[k] for k in keys[-3:])
            or abs(on["cameraRotation"]["y"]-90) > .02 or
            any(abs(on["cameraRotation"][k]) > .01 for k in ("x", "z"))):
        raise ValueError("Need matching north-up, top-down ground captures")
    return images, on, m, [refs[k]["sha256"] for k in (True, False)]


def sample_render(images, settings, grid, x, z):
    cell = grid.cell_at(x, z)
    result = dict(world_xz=[x,z], shading="unknown", terrain_flags=cell["raw_flags"])
    if cell["raw_flags"] & (2|4):
        return dict(result, reason="target_in_wall_or_structure")
    h, w = images[True].shape[:2]
    f = h/2 / math.tan(math.radians(settings["fieldOfView"])/2)
    c = settings["cameraPosition"]
    heights = grid.summary["height_samples"]
    # Enclose every possible terrain elevation, plus two pixels for the small
    # camera tilt, raster rounding and surveyed map registration.
    rect = []
    for elevation in (heights["minimum"], heights["maximum"]):
        if c["y"] <= elevation:
            raise ValueError("Camera is below the terrain height envelope")
        scale = f/(c["y"]-elevation)
        rect.append((w/2+(x-c["x"])*scale, h/2-(z-c["z"])*scale))
    xs, ys = zip(*rect)
    l, r = math.floor(min(xs))-2, math.ceil(max(xs))+3
    t, b = math.floor(min(ys))-2, math.ceil(max(ys))+3
    result["image_rect_xyxy_exclusive"] = [l,t,r,b]
    if not (0 <= l < r <= w and 0 <= t < b <= h):
        return dict(result, reason="outside_camera_footprint")
    current, reference = (images[k][t:b,l:r].astype(float) for k in (True,False))
    ref_light = reference.mean(axis=2)
    if np.percentile(ref_light,5) < 15:
        return dict(result, reason="reference_too_dark")
    error = abs(current-reference).max(axis=2)
    ratio = current.mean(axis=2)/np.maximum(1,ref_light)
    result.update(unchanged_fraction=float(np.mean(error <= 1)), median_light_ratio=float(np.median(ratio)))
    if np.all(error <= 2):
        result["shading"] = "clear"
    elif np.percentile(ratio,95) < .70 and np.all(ratio < .78):
        result["shading"] = "dark"
    else:
        result["reason"] = "mixed_shading_or_changing_surface"
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--grid", type=Path, required=True)
    p.add_argument("--at", type=float, required=True)
    p.add_argument("--world", type=float, nargs=2, action="append", required=True)
    a = p.parse_args()
    if not math.isfinite(a.at) or a.at < 0:
        p.error("Invalid game time")
    images, settings, manifest, hashes = load_pair(a.manifest, a.at)
    grid = parse_ngrid(a.grid.read_bytes())
    if (manifest["build"] != "16.22.836.1077" or grid.summary["raw_sha256"] not in {
        "28f6738003e01a0c13fa8a2f859d2947a8743606465b42139a24c423dd311bd9",
        "b7551b91dcdc3dec0228ff2df63483399b0b040552d2115b65d9fe1faf35bd93"}):
        p.error("The calibrated projection requires the reviewed 16.22 Map11 assets")
    from lol_coach.movement_1622 import MAP11_REPLAYS
    if manifest["replay_sha256"] not in MAP11_REPLAYS:
        p.error("This replay has no reviewed Map11 registration")
    print(json.dumps(dict(replay_sha256=manifest["replay_sha256"], at_seconds=a.at,
        perspective=manifest["perspective"], observer_team=None, png_sha256=hashes,
        points=[sample_render(images, settings, grid, x, z) for x,z in a.world]), indent=2))


if __name__ == "__main__":
    main()
