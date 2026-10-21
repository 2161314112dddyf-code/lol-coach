"""Acquire a local map-skin grid with version and archive evidence."""
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from .http import EvidenceClient, save_json
from .ngrid import parse_ngrid, parse_overlay, render_flags_png
from .wad import WadReader


def sha(data):
    return hashlib.sha256(data).hexdigest()


def keep(data_root, payload, suffix=".bin"):
    relative = Path("private/map-assets") / (sha(payload) + suffix)
    path = data_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {"evidence_path": relative.as_posix(), "sha256": sha(payload), "size_bytes": len(payload)}


def extract_map(root, game_dir, patch, skin="Default", offline=False, refresh=False):
    if not re.fullmatch(r"\d+\.\d+", patch) or not re.fullmatch(r"[A-Za-z0-9_]+", skin):
        raise ValueError("Map patch must be major.minor and skin a simple identifier")
    game = Path(game_dir).resolve()
    data_root = Path(root) / "data"
    metadata = {}
    for name in ("code-metadata.json", "content-metadata.json"):
        raw = (game / name).read_bytes()
        obj = json.loads(raw)
        version = obj.get("version", "")
        if not version.startswith(patch + "."):
            raise ValueError(f"{name} does not match requested patch {patch}")
        metadata[name] = {**keep(data_root, raw, ".json"), "source_path": str(game / name), "version": version}
    if metadata["code-metadata.json"]["version"].split("+")[0] != metadata["content-metadata.json"]["version"].split("+")[0]:
        raise ValueError("Code/content build metadata disagree")

    wad_path = game / "DATA/FINAL/Maps/Shipping/Map11.wad.client"
    before = wad_path.stat()
    wad = WadReader(wad_path)
    config_bytes, config_entry = wad.extract_bytes("data/maps/shipping/map11/map11.bin")
    config_entry.update(keep(data_root, config_bytes))
    # Directory previously reports about 9.2 MiB. Explicit map-only 16 MB cap.
    client = EvidenceClient(data_root, timeout=25, max_bytes=16_000_000)
    base_url = f"https://raw.communitydragon.org/{patch}/game/data/maps/shipping/map11/"
    opts = dict(offline=offline, refresh=refresh)
    binary_evidence, _ = client.fetch("cdragon-" + patch + "-map11.bin", base_url + "map11.bin", **opts)
    json_evidence, config = client.fetch("cdragon-" + patch + "-map11.bin.json", base_url + "map11.bin.json", expect_json=True, **opts)
    if binary_evidence["http_status"] != 200 or not isinstance(config, dict):
        raise ValueError("Public versioned map config unavailable; see data/attempts")
    if binary_evidence["sha256"] != sha(config_bytes):
        raise ValueError("Local map11.bin does not match public patch binary; refusing config association")
    skin_key = "Maps/Shipping/Map11/MapSkins/" + skin
    if skin_key not in config or "mNavigationMesh" not in config[skin_key]:
        raise ValueError("Selected map skin has no navigation mesh reference")
    path = config[skin_key]["mNavigationMesh"]
    if path.lower().encode() not in config_bytes.lower():
        raise ValueError("Public grid path is not present in the matching local config")
    raw_grid, grid_entry = wad.extract_bytes(path)
    grid_entry.update(keep(data_root, raw_grid, ".aimesh_ngrid"))
    grid = parse_ngrid(raw_grid)

    # These are config candidates; active-match composition is deliberately unknown.
    overlay_paths = set()
    def walk(value):
        if isinstance(value, dict):
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
        elif isinstance(value, str) and value.lower().endswith(".ngrid_overlay"):
            overlay_paths.add(value)
    walk(config)
    overlays = []
    for path in sorted(overlay_paths):
        raw, entry = wad.extract_bytes(path)
        entry.update(keep(data_root, raw, ".ngrid_overlay"))
        parsed = parse_overlay(raw, grid.width, grid.height)
        overlays.append({"source": entry, **parsed})

    with wad_path.open("rb") as stream:
        archive_sha = hashlib.file_digest(stream, "sha256").hexdigest()
    after = wad_path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise ValueError("WAD changed during extraction")
    bundle = data_root / "maps" / patch / skin
    bundle.mkdir(parents=True, exist_ok=True)
    record = {"schema_version": "0.1", "data_kind": "real_local_game_asset",
              "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
              "patch": patch, "map_id": 11, "map_skin": skin,
              "mode": None, "mode_reason": "No active match/replay skin or mode selection verified",
              "version_status": "local_code_content_build_and_public_config_binary_matched",
              "local_metadata": metadata,
              "archive": {"path": str(wad_path), "size_bytes": before.st_size,
                          "mtime_ns": before.st_mtime_ns, "sha256": archive_sha,
                          "format_version": "3.4", "entry_count": len(wad.entries),
                          "index_evidence": keep(data_root, wad.index_bytes, ".wad_index")},
              "public_config_binary": binary_evidence, "public_config_json": json_evidence,
              "local_config": config_entry, "selection": {"object": skin_key, "field": "mNavigationMesh", "path": grid_entry["internal_path"]},
              "base_grid": {"source": grid_entry, **grid.summary},
              "overlays": overlays,
              "license": {"asset_owner": "Riot Games", "reuse_permission": "not_determined", "distribution": "local_only_no_upload"},
              "limitations": ["Selected map skin is explicit; actual match selection remains unknown",
                              "Coordinates and flags have structural checks, not in-game movement calibration",
                              "Overlay trailing byte is unknown; overlays are decoded but not applied",
                              "No pathfinding, unit-radius clearance, dynamic obstacles or action timing"]}
    save_json(bundle / "manifest.json", record)
    save_json(bundle / "grid.json", {**grid.summary, "flags_rows_z_ascending": [list(grid.flags[i:i + grid.width]) for i in range(0, len(grid.flags), grid.width)]})
    render_flags_png(grid, bundle / "base_flags.png")
    print(f"Saved {bundle}; {grid.width} x {grid.height}, cell_size={grid.cell_size}, overlays={len(overlays)}")
    return bundle


def load_bundle(root, patch, skin="Default"):
    if not re.fullmatch(r"\d+\.\d+", patch) or not re.fullmatch(r"[A-Za-z0-9_]+", skin):
        raise ValueError("Invalid patch or skin")
    root = Path(root)
    manifest = json.loads((root / "data/maps" / patch / skin / "manifest.json").read_text(encoding="utf-8"))
    source = manifest["base_grid"]["source"]
    raw = (root / "data" / source["evidence_path"]).read_bytes()
    if sha(raw) != source["sha256"]:
        raise ValueError("Stored grid hash mismatch")
    return parse_ngrid(raw), manifest
