"""Bounded, replay-only field research for one exact client build.

Level suffixes were discovered using final levels and event sequences in the
known full replay. This is an observed codebook, not recovered client code.
Neither metadata nor an empty update stream establishes an initial level.
"""
from collections import Counter, defaultdict
import hashlib
import json
import math

VERSION = "16.20.824.8524"
DISCOVERY_SHA256 = "c08c6f1a4a87f1670a6156c6badfca15a21aa13c74eaa18dff5efdc26b94e7e0"
LEVEL_CODES = {
    0x19: 2, 0xBE: 3, 0xE4: 4, 0x65: 5, 0x83: 6, 0xDC: 7,
    0xB1: 8, 0xC8: 9, 0x1D: 10, 0x1B: 11, 0xC7: 12, 0xAA: 13,
    0x3E: 14, 0xE3: 15, 0x5D: 16, 0x4F: 17,
}
FINAL_FIELDS = (
    "SKIN", "TEAM", "LEVEL", "EXP", "GOLD_EARNED", "GOLD_SPENT",
    "MINIONS_KILLED", "NEUTRAL_MINIONS_KILLED", "CHAMPIONS_KILLED",
    "NUM_DEATHS", "ASSISTS", "TOTAL_TIME_SPENT_DEAD",
    *(f"ITEM{i}" for i in range(7)), *(f"SPELL{i}_CAST" for i in range(1, 5)),
    "SUMMONER_SPELL_1", "SUMMONER_SPELL_2", *(f"PERK{i}" for i in range(6)),
)


def read_metadata(raw):
    if len(raw) < 19 or raw[:5] != b"RIOT\x02":
        raise ValueError("Not an observed ROFL2 container")
    header_end = 15 + raw[14]
    version = raw[15:header_end].decode("ascii")
    if version != VERSION:
        raise ValueError(f"Unsupported exact build: {version}")
    size = int.from_bytes(raw[-4:], "little")
    start = len(raw) - 4 - size
    if size <= 0 or start - 256 < header_end:
        raise ValueError("Invalid metadata boundary")
    metadata = json.loads(raw[start:-4])
    if not isinstance(metadata, dict):
        raise ValueError("Metadata must be an object")
    stats = json.loads(metadata.get("statsJson", "[]"))
    if not isinstance(stats, list) or any(not isinstance(p, dict) for p in stats):
        raise ValueError("Invalid player metadata")
    return version, metadata, stats


def decode_level_payload(payload, version):
    """Return a candidate level only for observed suffixes and envelope shapes.

    Prefix bytes remain uninterpreted. In particular this does not claim to
    decode XP, the update reason, or non-champion entity levels.
    """
    if version != VERSION:
        raise ValueError("Unsupported exact build")
    if payload == b"\x19":
        return 2
    if len(payload) not in (2, 3) or payload[0] & 0xE0 != 0x20:
        raise ValueError("Unknown level payload shape")
    level = LEVEL_CODES.get(payload[-1])
    if level is None or level == 2:
        raise ValueError("Unobserved level suffix")
    return level


def location(packet):
    return {key: packet[key] for key in ("stream", "chunk", "offset", "channel")}


def analyze(raw, packets):
    version, metadata, stats = read_metadata(raw)
    digest = hashlib.sha256(raw).hexdigest()
    # Champion-like owner directory, not a decoded champion-name field.
    groups = defaultdict(dict)
    for p in packets:
        if p["stream"] == 2 and p["opcode"] == 0x445:
            owners = groups[p["chunk"]]
            if p["param"] in owners:
                raise ValueError("Duplicate owner in keyframe identity directory")
            if p["param"] >> 30 != 1:
                raise ValueError("Unexpected owner class")
            owners[p["param"]] = p
    if not groups:
        raise ValueError("No observed identity directory")
    first_chunk = min(groups)
    first = groups[first_chunk]
    owners = set(first)
    consistent_directory = all(set(g) == owners for g in groups.values())
    # The old kill/KDA investigation validated this mapping only on this hash.
    identities = {}
    if digest == DISCOVERY_SHA256:
        expected = set(range(0x40000034, 0x4000003E))
        if len(stats) != 10 or owners != expected:
            raise ValueError("Discovery replay identity invariant changed")
        identities = {0x40000034 + i: p for i, p in enumerate(stats)}
    events, rejected = [], []
    excluded = Counter()
    for p in packets:
        if p["stream"] != 1 or p["opcode"] != 0x229:
            continue
        if p["param"] not in owners:
            excluded["non_directory_owner"] += 1
            continue
        if p["channel"] != 1:
            excluded["unsupported_channel"] += 1
            continue
        time = p["time"]
        if not math.isfinite(time) or time < 0:
            raise ValueError("Invalid event timestamp")
        base = {
            "entity_id": hex(p["param"]), "packet_time_seconds": time,
            "packet": location(p), "payload_hex": p["payload"].hex(),
        }
        try:
            level = decode_level_payload(p["payload"], version)
        except ValueError as exc:
            rejected.append({**base, "level_candidate": None, "reason": str(exc)})
            continue
        events.append({**base, "level_candidate": level,
                       "champion": identities.get(p["param"], {}).get("SKIN"),
                       "evidence_kind": "observed_codebook_semantic_candidate",
                       "decision_input_eligible": False})
    checks = []
    for owner in sorted(owners):
        values = [e for e in events if e["entity_id"] == hex(owner)]
        levels = [e["level_candidate"] for e in values]
        ordered = all(a["packet_time_seconds"] <= b["packet_time_seconds"]
                      for a, b in zip(values, values[1:]))
        consecutive = all(b == a + 1 for a, b in zip(levels, levels[1:]))
        player = identities.get(owner, {})
        expected = int(player["LEVEL"]) if player.get("LEVEL") is not None else None
        rejected_count = sum(e["entity_id"] == hex(owner) for e in rejected)
        terminal = levels[-1] if levels else None
        matches = terminal == expected if expected is not None and terminal is not None else None
        status = ("FAIL" if not ordered or not consecutive or matches is False else
                  "PASS" if matches is True and rejected_count == 0 else "INSUFFICIENT_EVIDENCE")
        checks.append({
            "entity_id": hex(owner), "champion": player.get("SKIN"),
            "event_count": len(values), "first_observed_candidate": levels[0] if levels else None,
            "last_observed_candidate": terminal, "initial_level": None,
            "consecutive_observed_sequence": consecutive if levels else None,
            "time_ordered": ordered if levels else None,
            "metadata_final_level": expected, "final_level_matches": matches,
            "rejected_count": rejected_count, "status": status,
            "scope": "internal sequence/final-level agreement, not independent gameplay validation",
        })
    state_packets = []
    for opcode in (0x445, 0x2EF, 0x355):
        selected = [p for p in packets if p["stream"] == 2 and p["opcode"] == opcode
                    and p["param"] in owners]
        state_packets.append({"opcode": hex(opcode), "count": len(selected),
                              "payload_lengths": sorted({len(p["payload"]) for p in selected}),
                              "semantics": "owner-bound keyframe family; inner state unknown"})
    return {
        "schema": "replay-fields-research/v1", "version": version,
        "replay_sha256": digest, "game_length_metadata_ms": metadata.get("gameLength"),
        "scope": "retrospective research, not a time-t knowledge input",
        "packet_count": len(packets), "decision_input_eligible": False,
        "final_statistics": {"scope": "end_of_match_only", "not_a_timeline": True,
                             "players": [{k: p.get(k) for k in FINAL_FIELDS} for p in stats]},
        "identity_directory": {
            "champion_name_decoded_from_payload": False,
            "keyframe_count": len(groups), "same_owners_in_each_keyframe": consistent_directory,
            "association": "known-source-only metadata mapping" if identities else "unnamed owner candidates",
            "owners": [{"entity_id": hex(o), "champion": identities.get(o, {}).get("SKIN"),
                        "packet": location(first[o])} for o in sorted(owners)]},
        "level_events": events, "rejected_level_packets": rejected,
        "excluded_level_packet_counts": dict(excluded), "level_checks": checks,
        "keyframe_state_frontier": state_packets,
        "unavailable": ["payload_champion_name", "current_health", "current_resource",
                        "experience_timeline", "spell_cast_semantics", "inventory_timeline",
                        "visibility_at_time_t", "level_codes_1_and_18_plus"],
        "limitations": [
            "Suffix codebook was inferred post hoc from this full replay; checks are not blind holdout tests.",
            "Other replay sequences are a transfer check without independent numeric level labels.",
            "Unknown prefixes, gaps and levels outside the observed codebook remain unresolved.",
            "No events does not mean level 1; final metadata never fills earlier states.",
            "An opcode also used by non-champions must not turn those entities into players.",
        ],
    }
