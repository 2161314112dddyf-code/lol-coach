"""Audit independent ward positions and same-tick removal packets on reviewed ROFLs."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.movement_1622 import reviewed_ward_sources
from lol_coach.replay_container import packets
from lol_coach.vision_regions_1622 import ward_region_observations


def check(raw):
    wards = reviewed_ward_sources(raw)
    observations = {row["entity_id"]: row for row in ward_region_observations(raw, wards)}
    removal_counts = Counter(p["time"] for p in packets(raw) if p["stream"] == 1 and p["opcode"] == 0x57)
    comparisons = []
    for ward in wards:
        entity = ward["entity_id"]
        region = observations.get(entity)
        path = min(ward["positions"], key=lambda p: p["time_seconds"], default=None)
        distance = math.dist(path["world_xz"], region["center_xz"]) if path and region else None
        end = ward["end_seconds"]
        comparisons.append(dict(entity_id=hex(entity), team=ward["team_id"], region=region,
                                first_ward_path=path, distance=distance,
                                end_seconds=end, same_tick_removals=removal_counts[end] if end is not None else None))
    return dict(replay_sha256=hashlib.sha256(raw).hexdigest(), wards=len(wards), bound=len(observations),
                equal=sum(r["distance"] == 0 for r in comparisons),
                max_distance=max((r["distance"] for r in comparisons if r["distance"] is not None), default=None),
                removal_packets=removal_counts.total(), comparisons=comparisons)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path)
    args = parser.parse_args()
    print(json.dumps(check(args.replay.read_bytes()), indent=2))
