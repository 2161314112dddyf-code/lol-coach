"""Synthetic ROFL containers exercise the independent full-match sender assignment."""
import json
import struct

import pytest

from lol_coach.movement_1622 import VERSION
from lol_coach.replay_pings import build_ping_index
from scripts.audit_replay_pings import FOOTER_KINDS, audit
from test_replay_container import replay


def roster_row(champion, team=100, **kinds):
    return dict(SKIN=champion, TEAM=str(team),
                **{kind.upper() + "_PINGS": str(kinds.get(kind, 0)) for kind in FOOTER_KINDS})


def capture(stats, sends=(), version=VERSION):
    live = bytearray()
    for tick, (slot, kind) in enumerate(sends):
        body = bytes.fromhex("d562f79e14692a60553c") + bytes((kind, 0xC0 + slot, 0x93))
        live.extend(struct.pack("<BfIHI", 1, float(tick), len(body), 0x003F, 0) + body)
    raw = replay(version=version, payload=bytes(live))
    old_size = int.from_bytes(raw[-4:], "little")
    meta = json.dumps({"statsJson": json.dumps(stats)}).encode()
    return raw[:-4-old_size] + meta + len(meta).to_bytes(4, "little")


def test_blind_audit_is_independent_of_roster_order_and_does_not_unlock_player_projection():
    rows = [roster_row("Red", team=200, on_my_way=2), roster_row("Blue", assist_me=1), roster_row("Silent")]
    for order in (rows, list(reversed(rows))):
        raw = capture(order, [(8, 0x67), (1, 0x65), (1, 0x65)])
        report = audit(raw)
        index = report["index"]
        assert index["schema"] == "offline-footer-matched-pings/v1"
        assert [(e["sender_slot"], e["team_id"], e["sender_champion"]) for e in index["events"]] == [
            (8, 100, "Blue"), (1, 200, "Red"), (1, 200, "Red")]
        assert all("sender_entity_id" not in e for e in index["events"])
        assert report["validation"]["checked_cells"] == 42
        assert report["validation"]["independently_reviewed_roster"] is False
        assert build_ping_index(raw)["status"] == "unsupported_replay"


@pytest.mark.parametrize(("stats", "sends", "reason"), [
    ([roster_row("A", assist_me=1), roster_row("B", assist_me=1)], [(1, 0x67), (0, 0x67)], "ambiguous"),
    ([roster_row("A", assist_me=1)], [(1, 0x67), (0, 0x67)], "ambiguous"),
    ([roster_row("A"), roster_row("A")], [], "Duplicate"),
    ([roster_row("A", assist_me=1)], [], "Unmatched"),
    ([roster_row("A")], [(0, 0x67)], "Missing"),
    ([{"TEAM": "100", "SKIN": "A"}], [], "counters"),
    ([], [], "roster"),
])
def test_refuse_ambiguous_or_incomplete_assignment(stats, sends, reason):
    with pytest.raises(ValueError, match=reason):
        audit(capture(stats, sends))


def test_all_zero_counts_require_no_sender_assignment():
    report = audit(capture([roster_row("A"), roster_row("B")]))
    assert report["index"]["events"] == report["offline_sender_slot_bindings"] == []
    assert report["validation"]["checked_cells"] == 28


def test_refuse_different_container_build():
    with pytest.raises(ValueError, match="Unsupported ping build"):
        audit(capture([roster_row("A")], version="16.21.829.9102"))
