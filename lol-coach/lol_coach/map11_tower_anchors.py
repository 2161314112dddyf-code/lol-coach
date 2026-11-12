"""Locate fixed map landmarks from 16.22 turret names in native keyframes."""
import json
from pathlib import Path

from .replay_container import packets


def tower_landmarks(raw, version):
    """Bind known name bytes to static positions, retaining the first supporting time."""
    profile = json.loads(Path(__file__).with_name("profiles").joinpath("turret_map11_16_22.json").read_bytes())
    if version != profile["version"]:
        raise ValueError("Tower name profile does not match this replay")
    names = {bytes.fromhex(s): tower for tower in profile["towers"] for s in tower["wire_names"]}
    lengths = {len(s) for s in names}
    # Length codes depend on the string transform, even for equal lengths.
    headers = {(0x0e, 32): 0x76, (0x5d, 32): 0x11, (0x73, 32): 0x93,
               (0x0e, 31): 0x90, (0x5d, 31): 0x12, (0x73, 31): 0x17}
    result = {}
    conflicts = set()
    for p in packets(raw):
        if p["stream"] != 2 or p["opcode"] != profile["opcode"]:
            continue
        b = p["payload"]
        for length in lengths:
            if (len(b) <= 4 + length or b[3] != headers.get((b[4], length))
                    or b[4+length] != 0x10):
                continue
            tower = names.get(b[4:4+length])
            if tower is None:
                continue
            entity = p["param"]
            if entity in result and result[entity]["name"] != tower["name"]:
                conflicts.add(entity)
            if entity not in result or p["time"] < result[entity]["available_at_seconds"]:
                result[entity] = dict(name=tower["name"], team_id=tower["team"], role=tower["role"],
                                      map_reference_xz=tower["xz"], available_at_seconds=p["time"],
                                      basis="keyframe_turret_name_and_static_map_placement",
                                      source=dict(stream=2, chunk=p["chunk"], offset=p["offset"], opcode="0x402",
                                                  wire_name_hex=b[4:4+length].hex(),
                                                  geometry_sha256=profile["geometry_sha256"]))
    return {entity: row for entity, row in result.items() if entity not in conflicts}
