"""Estimate one ordinary vision source's contribution at supplied map positions."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.ngrid import parse_ngrid
from lol_coach.vision_geometry import source_coverage


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grid", type=Path, required=True, help="Base .aimesh_ngrid file")
    parser.add_argument("--source", type=float, nargs=2, required=True, metavar=("X", "Z"))
    parser.add_argument("--radius", type=float, required=True, help="Effective range in game units")
    parser.add_argument("--point", type=float, nargs=2, action="append", required=True, metavar=("X", "Z"))
    args = parser.parse_args()
    grid = parse_ngrid(args.grid.read_bytes())
    estimates = [dict(point_xz=point, **source_coverage(grid, args.source, point, args.radius))
                 for point in args.point]
    print(json.dumps(dict(scope="static_ground_sight_from_one_assumed_active_source",
                          grid_sha256=grid.summary["raw_sha256"], source_xz=args.source,
                          limits=["runtime overlays, height-specific rules and effects are unresolved",
                                  "only the listed points are evaluated; other sources could grant vision"],
                          points=estimates), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
