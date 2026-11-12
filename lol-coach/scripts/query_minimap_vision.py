"""Query ground points on one calibrated player's map at a recorded game time."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.vision_minimap import ground_classes, minimap_point


def checked_image(profile_path, spec, flag):
    data = (profile_path.parent / spec["file"]).read_bytes()
    if hashlib.sha256(data).hexdigest() != spec["sha256"]:
        raise ValueError("Calibration artifact hash mismatch")
    value = cv2.imdecode(np.frombuffer(data, np.uint8), flag)
    if value is None:
        raise ValueError("Invalid calibration image")
    return value


def sample_video(cap, seconds):
    cap.set(cv2.CAP_PROP_POS_MSEC, seconds * 1000)
    ok, frame = cap.read()
    actual = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
    if not ok or not np.isfinite(actual) or abs(actual - seconds) > 0.25:
        raise ValueError("Unable to resolve selected video frame precisely")
    return frame, actual


def last_frame_before(cap, seconds):
    if not np.isfinite(seconds) or seconds < 0:
        raise ValueError("Invalid cutoff PTS")
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0, seconds - 0.4) * 1000)
    sampled = None
    for _ in range(150):
        ok, frame = cap.read()
        actual = cap.get(cv2.CAP_PROP_POS_MSEC) / 1000
        if not ok or actual > seconds + 1e-8:
            break
        sampled = frame, actual
    if sampled is None or seconds - sampled[1] > 0.25:
        raise ValueError("No frame available immediately before the requested PTS")
    return sampled


def classify(frame, profile, background, mask):
    if list(frame.shape[:2]) != profile["frame_hw"]:
        raise ValueError("Frame resolution differs from calibration")
    x, y, w, h = profile["map_xywh"]
    return ground_classes(frame[y:y+h, x:x+w], background, mask, profile["palette_bgr"],
                          tolerance=profile["tolerance"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--team", type=int, choices=(100, 200), required=True)
    parser.add_argument("--at", type=int, required=True, help="Observed integer game clock (seconds)")
    parser.add_argument("--pts", type=float, help="Use the last frame at or before this video time")
    parser.add_argument("--emit-evidence", type=Path, help="Export requested points to a new evidence file")
    parser.add_argument("--point", action="append", nargs=2, type=float, default=[], metavar=("U", "V"))
    parser.add_argument("--world", action="append", nargs=2, type=float, default=[], metavar=("X", "Z"))
    args = parser.parse_args()
    profile = json.loads(args.profile.read_bytes())
    if profile.get("schema") != "minimap-ground-calibration/v1":
        raise ValueError("Unsupported minimap calibration")
    with args.video.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != profile["video_sha256"]:
            raise ValueError("Video does not match this HUD calibration")
    interval = profile["clock_pts"].get(str(args.at))
    header = dict(team_id=args.team, game_clock_seconds=args.at, video_sha256=profile["video_sha256"],
                  replay_sha256=profile["replay_sha256"], build=profile["build"])
    if args.team != profile["observer_team"] or interval is None:
        print(json.dumps(dict(**header, status="unknown", reason="viewpoint_or_clock_not_recorded")))
        return
    background = checked_image(args.profile, profile["background"], cv2.IMREAD_COLOR)
    mask = checked_image(args.profile, profile["terrain_mask"], cv2.IMREAD_GRAYSCALE)
    cap = cv2.VideoCapture(str(args.video))
    try:
        if args.pts is None:
            frame, actual = sample_video(cap, sum(interval)/2)
        else:
            frame, actual = last_frame_before(cap, args.pts)
    finally:
        cap.release()
    if not interval[0] - 0.001 <= actual <= interval[1] + 0.001:
        print(json.dumps(dict(**header, status="unknown", reason="frame_outside_observed_game_clock")))
        return
    classes = classify(frame, profile, background, mask)
    points = [minimap_point(classes, u, v) for u, v in args.point]
    west, south, width, height = profile["world_xz_extent"]
    for x, z in args.world:
        u, v = (x-west)/width, 1-(z-south)/height
        value = minimap_point(classes, u, v)
        value.update(input_world_xz=[x,z], position_basis="estimated_map_registration")
        points.append(value)
    counts = np.bincount(classes.ravel(), minlength=3)
    if args.emit_evidence is not None:
        if not points:
            raise ValueError("At least one point must be requested to export evidence")
        rows = {}
        for point in points:
            x, y = point["map_pixel_xy"]
            subject = f"ground:minimap-{x}-{y}"
            source = dict(kind="calibrated_player_minimap_shading", video_sha256=profile["video_sha256"],
                          game_clock_resolution_seconds=1, pts_first=actual, pts_last=actual, uv=point["uv"],
                          map_pixel_xy=[x,y], map_xywh=profile["map_xywh"], basis=point["basis"],
                          profile_sha256=hashlib.sha256(args.profile.read_bytes()).hexdigest())
            if "input_world_xz" in point:
                source["input_world_xz"] = point["input_world_xz"]
                source["position_basis"] = point["position_basis"]
            rows[subject] = dict(team_id=args.team, time_seconds=args.at, subject=subject,
                                 mode="sample", visible=point["visible"], source=source)
        index = dict(schema="vision-evidence/v1", version=profile["build"], source_sha256=profile["replay_sha256"],
                     end_seconds=profile["end_seconds"], observations=list(rows.values()))
        with args.emit_evidence.open("x", encoding="utf8") as stream:
            json.dump(index, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps(dict(**header, status="sampled", pts=actual, map_width=classes.shape[1],
                          map_height=classes.shape[0], whole_map_pixel_count=int(classes.size),
                          classified_pixels=int(counts[1]+counts[2]), visible_pixels=int(counts[1]),
                          fogged_pixels=int(counts[2]), unknown_pixels=int(counts[0]), points=points)))


if __name__ == "__main__":
    main()
