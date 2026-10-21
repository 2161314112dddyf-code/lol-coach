"""Offline checks on acquired real map assets, distinct from synthetic pytest."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lol_coach.http import save_json
from lol_coach.map_pipeline import load_bundle
from lol_coach.ngrid import parse_overlay

grid, manifest = load_bundle(ROOT, "16.20", "Default")
bundle = ROOT / "data/maps/16.20/Default"
references = [*manifest["local_metadata"].values(), manifest["archive"]["index_evidence"],
              manifest["local_config"], manifest["public_config_binary"], manifest["public_config_json"],
              manifest["base_grid"]["source"], *[o["source"] for o in manifest["overlays"]]]
for r in references:
    assert hashlib.sha256((ROOT / "data" / r["evidence_path"]).read_bytes()).hexdigest() == r["sha256"]
assert manifest["local_config"]["sha256"] == manifest["public_config_binary"]["sha256"]
assert grid.summary == {k: manifest["base_grid"][k] for k in grid.summary}
normalized = json.loads((bundle / "grid.json").read_text(encoding="utf-8"))
assert tuple(v for row in normalized["flags_rows_z_ascending"] for v in row) == grid.flags
for overlay in manifest["overlays"]:
    raw = (ROOT / "data" / overlay["source"]["evidence_path"]).read_bytes()
    parsed = parse_overlay(raw, grid.width, grid.height)
    assert parsed == {k: overlay[k] for k in parsed}
# Check all cell centers that lie inside the declared (partly filled) bounds.
checked = 0
for z in range(grid.height):
    for x in range(grid.width):
        wx = min(grid.bounds_min[0] + (x + 0.5) * grid.cell_size, grid.bounds_max[0] - 0.001)
        wz = min(grid.bounds_min[2] + (z + 0.5) * grid.cell_size, grid.bounds_max[2] - 0.001)
        q = grid.cell_at(wx, wz)
        assert (q["cell_x"], q["cell_z"]) == (x, z)
        checked += 1
report = {"status": "passed", "data_kind": "real_local_game_asset_offline_smoke",
          "patch": "16.20", "map_skin": "Default", "raw_evidence_hashes_checked": len(references),
          "cell_coordinate_roundtrips_checked": checked, "overlays_reparsed": len(manifest["overlays"]),
          "base_grid_sha256": grid.summary["raw_sha256"],
          "checks": ["raw hashes", "local/public config binary identity", "all stored cell coordinates", "exact normalized flags", "overlay regions and tails", "header-derived coordinate roundtrips"],
          "not_tested": ["in-game coordinate calibration", "collision/passability", "active map skin", "overlay application", "path timing"]}
save_json(ROOT / "reports/map_smoke.json", report)
print(json.dumps(report, indent=2))
