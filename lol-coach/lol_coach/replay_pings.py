"""Player-issued signals on hash-reviewed 16.22 ROFL captures.

The timestamp is a live packet timestamp. The footer provides independent
whole-match validation in the audit, never the time or contents of an event.
"""
import hashlib

from .hero_sight import reviewed_heroes
from .movement_1622 import VERSION
from .ping_regions import marker_observations, verified_region
from .replay_container import container_info, packets


OPCODE = 0x003F
TYPE_BYTES = {
    0x64: "get_back", 0x65: "on_my_way", 0x66: "enemy_vision",
    0x67: "assist_me", 0x69: "all_in", 0x6B: "retreat",
    0x7A: "enemy_missing", 0x7E: "push", 0x7F: "need_vision",
}
PING_KINDS = frozenset((*TYPE_BYTES.values(), "command"))
# The reviewed channel semantics refer to issuance, not individual delivery.
TEAM_CHANNEL_KINDS = frozenset(("retreat", "push", "on_my_way", "all_in", "assist_me",
                                "need_vision", "enemy_missing", "enemy_vision"))
CHANNEL_REFERENCE = "https://support.riotgames.com/en-us/league-of-legends/gameplay/smart-ping"


def decode_ping_fields(packet):
    """Read the wire slot and kind without assuming a roster or a network object ID."""
    if (packet["stream"], packet["channel"], packet["opcode"]) != (1, 1, OPCODE):
        return None
    data = packet["payload"]
    if not data:
        raise ValueError("empty_ping_envelope")
    if not data[0] & 0x40:
        return None
    if (packet["param"] != 0 or len(data) not in (12, 13, 14, 15, 16)
            or data[0] & 0x7F not in (0x4D, 0x55, 0x5D, 0x65, 0x6D, 0x75, 0x7D)
            or data[-1] != 0x93 or not 0xC0 <= data[-2] <= 0xC9):
        raise ValueError("unreviewed_player_ping_shape")
    flag = data[1] & 0xFC
    # The second ten-player capture also has two commands with three bytes
    # between the position fields and sender. Their contents remain opaque.
    long_command_shape = len(data) == 15 and data[0] & 0x7F in (0x5D, 0x6D) and data[-3] == 0x72
    if flag == 0xA0 and (len(data) in (12, 14) or long_command_shape):
        kind = "command"
    elif flag in (0x00, 0x20, 0x60, 0xC0) and len(data) in (13, 15, 16) and data[10] in TYPE_BYTES:
        kind = TYPE_BYTES[data[10]]
    else:
        raise ValueError("unreviewed_player_ping_kind")
    source = {k: packet[k] for k in ("stream", "channel", "opcode", "chunk", "offset")}
    event = dict(time_seconds=packet["time"], sender_slot=data[-2] - 0xC0,
                 kind=kind, marker_xz=None, source=source)
    if kind in TEAM_CHANNEL_KINDS:
        event["channel"] = "team"
    return event


def decode_ping_packet(packet, heroes):
    event = decode_ping_fields(packet)
    if event is None:
        return None
    entity = 0x400000AE + event.pop("sender_slot")
    if entity not in heroes:
        raise ValueError("unreviewed_player_ping_sender")
    hero = heroes[entity]
    return dict(**event, sender_entity_id=hex(entity), sender_champion=hero["name"], team_id=hero["team_id"])


def build_ping_index(raw):
    """Build one replay-wide host index. Only the POV projection belongs in a frame."""
    digest = hashlib.sha256(raw).hexdigest()
    heroes = reviewed_heroes(digest)
    index = dict(schema="review-ping-index/v1", build=None, source_sha256=digest,
                 status="unsupported_replay", events=[])
    if not heroes:
        return index
    build = container_info(raw)["version"]
    index["build"] = build
    if build != VERSION:
        return index
    markers, report_hash = marker_observations(digest, build)
    for packet in packets(raw):
        event = decode_ping_packet(packet, heroes)
        if event is not None:
            measurement = markers.pop((packet['chunk'], packet['offset']), None)
            if measurement is not None:
                event['marker_region'] = verified_region(event, packet, measurement)
                event['marker_report_sha256'] = report_hash
            index["events"].append(event)
    if markers:
        raise ValueError('unmatched_ping_hud_packets')
    index["events"].sort(key=lambda e: (e["time_seconds"], e["source"]["chunk"], e["source"]["offset"]))
    index["status"] = "verified"
    return index
