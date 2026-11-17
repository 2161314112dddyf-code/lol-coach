"""Compare decoded live signals with separate player-by-category footer counts."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from lol_coach.http import save_json
from lol_coach.movement_1622 import VERSION
from lol_coach.replay_container import container_info, packets
from lol_coach.replay_pings import OPCODE, build_ping_index, decode_ping_fields


FOOTER_KINDS = frozenset({
    "all_in", "assist_me", "basic", "command", "danger", "enemy_missing", "enemy_vision",
    "get_back", "hold", "need_vision", "on_my_way", "push", "retreat", "vision_cleared",
})


def footer_counts(row):
    counts = {field.removesuffix("_PINGS").lower(): value
              for field, value in row.items() if field.endswith("_PINGS")}
    if counts.keys() != FOOTER_KINDS or any(not str(value).isascii() or not str(value).isdecimal()
                                            for value in counts.values()):
        raise ValueError("Incomplete or unrecognized player ping counters")
    return {kind: int(value) for kind, value in counts.items()}


def match_sending_slots(events, stats):
    """Assign only active slots; the order of footer rows has no significance."""
    if not isinstance(stats, list) or not 1 <= len(stats) <= 10:
        raise ValueError("Missing or unsupported player ping roster")
    by_actor = {}
    for row in stats:
        if not isinstance(row, dict) or str(row.get("TEAM")) not in ("100", "200"):
            raise ValueError("Invalid ping roster team")
        champion = row.get("SKIN")
        if not isinstance(champion, str) or not champion.strip():
            raise ValueError("Missing ping roster champion")
        actor = champion, int(row["TEAM"])
        if actor in by_actor:
            raise ValueError("Duplicate ping roster identity")
        by_actor[actor] = footer_counts(row)

    live = defaultdict(Counter)
    for event in events:
        live[event["sender_slot"]][event["kind"]] += 1
    bound = {}
    for slot, counts in live.items():
        candidates = [actor for actor, totals in by_actor.items() if counts == Counter(totals)]
        if len(candidates) != 1 or candidates[0] in bound.values():
            raise ValueError("Missing or ambiguous full-match sender count vector")
        bound[slot] = candidates[0]
    if set(bound.values()) != {actor for actor, counts in by_actor.items() if any(counts.values())}:
        raise ValueError("Unmatched positive footer ping counters")
    return bound, by_actor


def audit(raw):
    info = container_info(raw)
    if info["version"] != VERSION:
        raise ValueError("Unsupported ping build")
    stats = json.loads(info["metadata"].get("statsJson", "[]"))
    family = [p for p in packets(raw) if (p["stream"], p["channel"], p["opcode"]) == (1, 1, OPCODE)]
    fields = [event for packet in family if (event := decode_ping_fields(packet)) is not None]
    fields.sort(key=lambda e: (e["time_seconds"], e["source"]["chunk"], e["source"]["offset"]))
    slots, footer = match_sending_slots(fields, stats)
    blind = []
    for event in fields:
        champion, team = slots[event["sender_slot"]]
        blind.append(dict(**event, sender_champion=champion, team_id=team))
    index = build_ping_index(raw)
    compared = 0
    if index["status"] == "verified":
        for event, reviewed in zip(blind, index["events"], strict=True):
            if any(reviewed[key] != value for key, value in event.items() if key != "sender_slot"):
                raise ValueError("Blind sender mapping disagrees with reviewed events")
            compared += 1
    else:
        # A different schema prevents a full-match count assignment from entering a frozen player frame.
        index = dict(schema="offline-footer-matched-pings/v1", status="offline_audit_only",
                     build=info["version"], source_sha256=index["source_sha256"], events=blind)
    observed = Counter((r["sender_champion"], r["team_id"], r["kind"]) for r in blind)
    matrix = []
    for (champion, team), totals in footer.items():
        counts = {}
        for kind, wanted in totals.items():
            got = observed[champion, team, kind]
            counts[kind] = dict(footer=wanted, live=got)
        matrix.append(dict(champion=champion, team_id=team, counts=counts))
    slot_bindings = [dict(slot=slot, champion=actor[0], team_id=actor[1]) for slot, actor in sorted(slots.items())]
    return dict(index=index, offline_sender_slot_bindings=slot_bindings,
                validation=dict(all_0x003f_live_packets=len(family), accepted=len(fields),
                bit_clear_excluded=len(family) - len(fields), blind_compared_to_reviewed_events=compared,
                independently_reviewed_roster=index["status"] == "verified",
                checked_cells=sum(len(row["counts"]) for row in matrix), cells=matrix,
                footer_latency_field_excluded=True, issue_time_from_live_packets=True))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("replay", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    private = Path(__file__).resolve().parents[1] / "data/private"
    if not args.output.resolve().is_relative_to(private.resolve()):
        parser.error("Write raw player event evidence under data/private")
    for path in args.replay:
        result = audit(path.read_bytes())
        save_json(args.output / (path.stem + ".json"), result)
        summary = {k: v for k, v in result["validation"].items() if k != "cells"}
        print(json.dumps(dict(replay=path.stem, **summary)))


if __name__ == "__main__":
    main()
