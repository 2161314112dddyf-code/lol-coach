"""Estimate ordinary ground vision from placed, source-bound trinkets on Map11."""
from hashlib import sha256
import json
import math
import re

from .ngrid import parse_ngrid, parse_overlay
from .vision_geometry import source_coverage
from .wad import WadReader


def load_terrain(game_dir, replay_version):
    """Load the two relevant base meshes and potential changes from this build."""
    build = replay_version.split(".")
    expected = ".".join(build[:2] + ["".join(build[2:])])
    for name in ("code-metadata.json", "content-metadata.json"):
        actual = json.loads((game_dir / name).read_bytes())["version"].split("+")[0]
        if actual != expected:
            raise ValueError("Installed assets do not match the replay build")
    wad = WadReader(game_dir / "DATA/FINAL/Maps/Shipping/Map11.wad.client")
    grids, overlays = [], []
    for variant in (2, 3):
        path = f"ASSETS/Maps/NavGrid/Map11/AIPath_SRX_{variant}.aimesh_ngrid"
        data, _ = wad.extract_bytes(path)
        grids.append(parse_ngrid(data))
    if any((g.bounds_min, g.bounds_max, g.width, g.height, g.cell_size) !=
           (grids[0].bounds_min, grids[0].bounds_max, grids[0].width, grids[0].height, grids[0].cell_size)
           for g in grids[1:]):
        raise ValueError("Map variants are in different coordinate frames")
    config, _ = wad.extract_bytes("data/maps/shipping/map11/map11.bin")
    for name in sorted(set(re.findall(rb"[A-Za-z_0-9/.]+\.ngrid_overlay", config))):
        data, _ = wad.extract_bytes(name.decode())
        for r in parse_overlay(data, grids[0].width, grids[0].height)["regions"]:
            overlays.append((r["x"], r["z"], r["x"] + r["width"], r["z"] + r["height"]))
    for model, radius, digest in WARD_DEFINITIONS.values():
        definition, ref = wad.extract_bytes(f"data/characters/{model}/{model}.bin")
        if ref["sha256"] != digest or sha256(definition).hexdigest() != digest:
            raise ValueError(f"Unreviewed {model} definition for the {radius:g}-unit radius")
    return grids, overlays


# perceptionBubbleRadius on the matching CharacterRecords.
WARD_DEFINITIONS = {
    "sight_ward": ("SightWard", 900.0, "089b2fbf68c4ac8969af160757522342cb522c41339ea8d48d88b1970064668a"),
    "control_ward": ("JammerDevice", 900.0, "b2c538efeb9866c43ddd947665b0b1797f05c107e9367a5bdc404f4daafcbf38"),
    "farsight_ward": ("BlueTrinket", 500.0, "5750d3487631a4241377f8e68aaa25202c00b13b722dc058285cb93b9a8cd7f2"),
}


def terrain_estimate(grids, overlays, origins, target, radius):
    results = [source_coverage(g, source, target, radius) for source in origins for g in grids]
    cells = [grids[0].cell_at(*p) for p in [*origins, target]]
    xs, zs = [c["cell_x"] for c in cells], [c["cell_z"] for c in cells]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    potential_overlay = any(left <= x1 and x0 < right and low <= z1 and z0 < high
                            for left, low, right, high in overlays)
    states = {r["estimate"] for r in results}
    estimate = next(iter(states)) if len(states) == 1 else "indeterminate"
    if potential_overlay and estimate != "outside_radius":
        estimate = "indeterminate"
    return estimate, results, potential_overlay


def nearby_minion_sources(minions, team, target, grids, overlays, max_age):
    sources = []
    for m in minions:
        pos = m["position"]
        radius = m.get("vision_radius_units")
        if m["team_id"] != team or not pos or not radius or pos["age_seconds"] > max_age:
            continue
        distance = math.dist(pos["world_xz"], target)
        if distance > radius:
            continue
        estimate, _, _ = terrain_estimate(grids, overlays, [pos["world_xz"]], target, radius)
        sources.append(dict(entity_id=hex(m["entity_id"]), lane=m["lane"], kind=m["minion_class"],
                            radius_units=radius, distance_units=distance, position=pos, estimate=estimate))
    return dict(sources=sources, maximum_sample_age_seconds=max_age,
                basis="ordinary lane minion sight at last sampled path start; movement after sample unresolved")


def ward_contributions(wards, team, at, target, grids, overlays):
    """Return a conditional source contribution. Team fog needs separate evidence."""
    # Validate the coordinates even if this team has no bound ward at the time.
    grids[0].cell_at(*target)
    contributions = []
    for ward in wards:
        family = ward.get("family") or {3340:"sight_ward", 2055:"control_ward"}.get(ward["item_id"])
        if (ward["team_id"] != team or family not in WARD_DEFINITIONS or ward["start_seconds"] > at
                or (ward["end_seconds"] is not None and at >= ward["end_seconds"])):
            continue
        positions = [p for p in ward["positions"] if p["time_seconds"] <= at]
        region = ward.get("spatial_record")
        if region and region["time_seconds"] <= at:
            positions.append(dict(time_seconds=region["time_seconds"], world_xz=region["center_xz"],
                                  source=region["source"]))
        else:
            region = None
        if not positions:
            continue
        latest = max(positions, key=lambda p: p["time_seconds"])
        source = latest["world_xz"]
        model, radius, digest = WARD_DEFINITIONS[family]
        origins = [source]
        if region and region["center_xz"] != source:
            origins.append(region["center_xz"])
        estimate, results, potential_overlay = terrain_estimate(grids, overlays, origins, target, radius)
        if family == "farsight_ward":
            # Its reveal on placement/detection and ability to see through terrain
            # are not the ordinary ward ray. Keep the native source and asset value.
            estimate = "special_reveal_unresolved"
        contributions.append(dict(entity_id=hex(ward["entity_id"]), item_id=ward["item_id"], source_xz=source,
                                  family=family, position_sample_seconds=latest["time_seconds"],
                                  region_center_xz=region["center_xz"] if region else None,
                                  region_source=region["source"] if region else None,
                                  start_seconds=ward["start_seconds"], source_record=latest["source"],
                                  placement_record=ward["start_source"], distance_units=results[0]["distance_units"],
                                  radius_units=radius, estimate=estimate, possible_overlay=potential_overlay,
                                  radius_basis=f"conditional_on_ordinary_{model}_radius", asset_sha256=digest,
                                  activity_basis="placed_and_no_removal_observed_by_cutoff; assumes enabled at sampled location",
                                  extra_reveals_modeled=False,
                                  mesh_results=[] if family == "farsight_ward" else
                                      [(r["estimate"], r["reason"]) for r in results]))
    return dict(team_id=team, at_seconds=at, target_xz=target, contributions=contributions,
                observed_team_ground_visibility=None)
