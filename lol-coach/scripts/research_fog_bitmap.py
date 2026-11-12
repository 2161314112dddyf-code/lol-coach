"""Compare contiguous 128x128 bit planes in real keyframes to recorded HUD ground."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.replay_container import container_info, packets
from scripts.query_minimap_vision import checked_image, classify, sample_video


SIDE = 128
BYTES = SIDE * SIDE // 8


def hexhash(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def orientations(labels):
    for turns in range(4):
        rotated = np.rot90(labels, turns)
        for reflected in (False, True):
            yield (turns, reflected), np.fliplr(rotated) if reflected else rotated


def compare_plane(payload, labels):
    """Search all bit starts, both bit orders/polarities, eight map orientations.

    Scores are the average of visible and fogged recall; unknown pixels do
    not vote. The best fit is intentionally in-sample, to favor the hypothesis.
    """
    if labels.shape != (SIDE, SIDE) or len(payload) < BYTES:
        raise ValueError("Expected a 128-square map and at least 2048 payload bytes")
    visible, dark = (np.sum(labels == n) for n in (1, 2))
    if not visible or not dark:
        raise ValueError("Need both independently observed classes")
    best = {"balanced_accuracy": -1}
    for bitorder in ("little", "big"):
        bits = np.unpackbits(np.frombuffer(payload, np.uint8), bitorder=bitorder)
        signal = bits.astype(np.float32).reshape(1, -1)
        for (turns, reflected), view in orientations(labels):
            weights = (view == 1) / visible - (view == 2) / dark
            kernel = np.ascontiguousarray(weights.reshape(1, -1), dtype=np.float32)
            diff = cv2.matchTemplate(signal, kernel, cv2.TM_CCORR).ravel()
            start = int(np.argmax(np.abs(diff)))
            score = (1 + abs(float(diff[start]))) / 2
            if score > best["balanced_accuracy"]:
                best = dict(balanced_accuracy=round(score, 6), start_bit=start, bitorder=bitorder,
                            one_is_visible=bool(diff[start] > 0), quarter_turns=turns, reflected=reflected)
    return best


def substitution_bound(payload, labels):
    """Upper bound for an aligned plane under ANY constant byte substitution.

    Eight fully observed equal cells must encode to one byte. Grant each class
    its most frequent byte independently, which can only inflate the result.
    """
    source = np.frombuffer(payload, np.uint8)
    starts = np.arange(len(source) - BYTES + 1)
    best = None
    for (turns, reflected), view in orientations(labels):
        groups = view.reshape(-1, 8)
        locations = [np.flatnonzero(np.all(groups == value, axis=1)) for value in (1, 2)]
        if min(map(len, locations)) < 5:
            continue
        scores = np.zeros(len(starts))
        for cells in locations:
            values = source[starts[:, None] + cells] + (starts[:, None] << 8)
            counts = np.bincount(values.ravel(), minlength=len(starts) * 256).reshape(-1, 256)
            scores += counts.max(axis=1) / len(cells) / 2
        offset = int(np.argmax(scores))
        if best is None or scores[offset] > best["upper_bound"]:
            best = dict(upper_bound=round(float(scores[offset]), 6), start_byte=offset,
                        quarter_turns=turns, reflected=reflected,
                        all_lit_groups=len(locations[0]), all_fogged_groups=len(locations[1]))
    return best


def capture_labels(cap, profile, background, mask, clock):
    interval = profile["clock_pts"].get(str(clock))
    if interval is None:
        return None
    frame, pts = sample_video(cap, sum(interval) / 2)
    ground = classify(frame, profile, background, mask)
    ys, xs = [(np.arange(SIDE) + .5) * size / SIDE for size in ground.shape]
    return pts, ground[np.ix_(ys.astype(int), xs.astype(int))]


def audit(replay, calibration=None, video=None):
    raw = replay.read_bytes()
    report = dict(sha256=hashlib.sha256(raw).hexdigest(), build=container_info(raw)["version"])
    stream_counts = Counter()
    frames = {}
    for packet in packets(raw):
        stream_counts[packet["stream"]] += 1
        if packet["stream"] != 2:
            continue
        frame = frames.setdefault(packet["chunk"], {"at": packet["time"], "large": []})
        if len(packet["payload"]) >= BYTES:
            frame["large"].append(packet)
    report.update(stream_counts=dict(stream_counts), keyframes=len(frames))
    profile = cap = None
    if calibration:
        profile = json.loads(calibration.read_bytes())
        if report["sha256"] != profile["replay_sha256"] or hexhash(video) != profile["video_sha256"]:
            raise ValueError("Calibration and source identity differ")
        background = checked_image(calibration, profile["background"], cv2.IMREAD_COLOR)
        mask = checked_image(calibration, profile["terrain_mask"], cv2.IMREAD_GRAYSCALE)
        cap = cv2.VideoCapture(str(video))
        report["calibration_sha256"] = hexhash(calibration)
        report["video_sha256"] = profile["video_sha256"]
    summaries = []
    try:
        for chunk, frame in frames.items():
            tests = []
            for delay in ((0, 60) if cap else ()):
                clock = round(frame["at"]) - delay
                result = capture_labels(cap, profile, background, mask, clock)
                if result is None:
                    continue
                pts, labels = result
                for p in frame["large"]:
                    tests.append(dict(clock=clock, video_pts=pts, assumed_delay=delay,
                                      visible_samples=int((labels == 1).sum()), fogged_samples=int((labels == 2).sum()),
                                      opcode=hex(p["opcode"]), packet_offset=p["offset"],
                                      literal=compare_plane(p["payload"], labels),
                                      byte_substitution=substitution_bound(p["payload"], labels)))
            summaries.append(dict(chunk=chunk, at=frame["at"], tests=tests,
                                  candidate_packets=[dict(opcode=hex(p["opcode"]), payload_bytes=len(p["payload"]),
                                                          offset=p["offset"]) for p in frame["large"]]))
    finally:
        if cap:
            cap.release()
    return dict(**report, frames=summaries)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--video", type=Path)
    args = parser.parse_args()
    if bool(args.profile) != bool(args.video):
        parser.error("--profile and --video are required together")
    print(json.dumps(audit(args.replay, args.profile, args.video), indent=2))


if __name__ == "__main__":
    main()
