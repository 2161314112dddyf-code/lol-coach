"""Decode coordinates of ward-associated spatial records in build 16.22.836.1077."""
import hashlib
import struct
from collections import defaultdict

from .replay_container import container_info, packets


VERSION = "16.22.836.1077"
OPCODE = 0x369
# Identified from paired map landmarks, then validated against an independent
# packet family's X/Z in a second match. Only the two coordinate words use it.
WIRE_TO_FLOAT_BYTE = bytes.fromhex(
    "4a415eb800dfba0e92218f82077e6f6a0bfdc9a69f49f71187462319ad13b58e"
    "a15c9b3d4fc193762f537a9adb84a7360fee80af2e90d8d2543c48e0d9ef0de9"
    "aa616eb955621dd47f7129dc7834e65198e117e51cf495374df869aca4ccda884"
    "4ea0325b7c8f2dea8e44372e80c14a089a3c6326852d0d394b491f9f5e245012"
    "4d12c5af03f864b793583d75b4005cbbb127d9d81b6c0bf9cbcf3ca224ebe6d1f"
    "67b1164c64600a59b37bfbb27085f63ec3c5083b8c383a6ccea2ed8aff27e35f"
    "759996332b5dcf9e0402564763c797e7c2fa302add7cbd50eb66fc091a1b10391"
    "5cdae06d5658b20a9578da531f1742d586bc4d67773b0421e18feab26ec28"
)
SIDES = {0x71: 100, 0x77: 200}


def _handle(payload, coordinate_offset):
    value = 0
    for i, wire in enumerate(payload[11:min(16, coordinate_offset)]):
        unmasked = wire ^ 0x10
        rotated = ((unmasked << 2) | (unmasked >> 6)) & 255
        adjacent_swap = ((rotated & 85) << 1) | ((rotated >> 1) & 85)
        byte = (adjacent_swap + 87) & 255
        value |= (byte & 127) << (7 * i)
        if byte < 128:
            return value if value and (i == 0 or byte) and value <= 0xffffffff else None
    return None


def decode_spatial_record(payload):
    """Recognize only the checked Map11 payload layouts. Returns no sight flag."""
    signature = payload[1:5]
    if signature == bytes.fromhex("c2445701") and len(payload) == 36:
        family, offset = "tower_associated", 19
    elif signature == bytes.fromhex("c2c24b01") and len(payload) in (25, 26):
        family, offset = "ordinary_or_control_ward_associated", len(payload) - 8
    elif signature == bytes.fromhex("c2c29c01") and len(payload) == 22:
        family, offset = "farsight_ward_associated", 14
    else:
        return None
    team = SIDES.get(payload[10])
    if team is None:
        return None
    z, x = struct.unpack(">ff", payload[offset:offset + 8].translate(WIRE_TO_FLOAT_BYTE))
    handle = _handle(payload, offset)
    if handle is None or not (0 <= x <= 15000 and 0 <= z <= 15000):
        return None
    return dict(family=family, team_id=team, region_handle=handle,
                center_xz=[x, z], payload_offset_zx=offset)


def ward_region_observations(raw, wards):
    """Bind the placement tick/family/side of independently identified wards.

    Ambiguous co-placements and packets without a matching ward remain unbound.
    The centre is the value carried by this packet. Path samples can differ.
    """
    if container_info(raw)["version"] != VERSION:
        raise ValueError("Unsupported spatial record build")
    groups = defaultdict(list)
    for ward in wards:
        item = ward.get("item_id")
        family = ward.get("family")
        if family in ("sight_ward", "control_ward") or item in (3340, 2055):
            kind = "ordinary_or_control_ward_associated"
        elif family == "farsight_ward":
            kind = "farsight_ward_associated"
        else:
            continue
        groups[ward["start_seconds"], ward["team_id"], kind].append(ward["entity_id"])
    candidates = defaultdict(list)
    for p in packets(raw):
        if p["stream"] != 1 or p["opcode"] != OPCODE or p["param"] != 0:
            continue
        row = decode_spatial_record(p["payload"])
        if row is None:
            continue
        key = (p["time"], row["team_id"], row["family"])
        if key in groups:
            ref = dict(stream=p["stream"], chunk=p["chunk"], offset=p["offset"], opcode=hex(OPCODE),
                       payload_sha256=hashlib.sha256(p["payload"]).hexdigest())
            candidates[key].append(dict(**row, time_seconds=p["time"], source=ref))
    observations = []
    for key, rows in candidates.items():
        if len(groups[key]) != 1 or len({tuple(row["center_xz"]) for row in rows}) != 1:
            continue
        # A single placement may register two regions at the identical centre.
        # Their shared location is known, their individual roles are unresolved.
        observations.append(dict(**rows[0], entity_id=groups[key][0],
                                 coincident_handles=[r["region_handle"] for r in rows],
                                 coincident_sources=[r["source"] for r in rows]))
    return observations
