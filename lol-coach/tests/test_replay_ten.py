"""Synthetic behavior checks; corpus evidence is generated separately."""
import pytest

from lol_coach.replay_ten import category_coverage, combat_events, footer_categories, movement_records, number, state_at

A, B, C = 0x40000034, 0x40000035, 0x40000036


def p(op, owner=A, time=10, size=5, chunk=1, stream=1):
    return dict(opcode=op, param=owner, time=time, payload=b"x" * size,
                chunk=chunk, stream=stream, channel=1, offset=0)


def kill_sequence(time=10):
    return [p(0x3B, A, time), p(0x3B, C, time), p(0x3B, B, time), p(0x28, A, time)]


def test_victim_assist_killer_order_and_respawn():
    kills, life = combat_events(kill_sequence() + [p(0x45E, A, 20, 13)], {A, B, C})
    assert kills[0]["victim_entity_id"] == hex(A)
    assert kills[0]["killer_entity_id"] == hex(B)
    assert kills[0]["assist_entity_ids"] == [hex(C)]
    assert life["intervals"][0]["duration_seconds"] == 10


def test_no_champion_killer_does_not_invent_turret():
    kills, life = combat_events([p(0x3B), p(0x28)], {A})
    assert kills[0]["killer_entity_id"] is None
    assert kills[0]["non_champion_killer_identity"] is None
    assert life["intervals"][0]["respawn_seconds"] is None
    assert life["intervals"][0]["duration_seconds"] is None


@pytest.mark.parametrize("owners", [[B, A], [A, B, B], [A, 0x40000999]])
def test_bad_owner_sequence_rejected(owners):
    with pytest.raises(ValueError, match="participation"):
        combat_events([*[p(0x3B, owner) for owner in owners], p(0x28)], {A, B, C})


@pytest.mark.parametrize("change", [{"time": 11}, {"chunk": 2}])
def test_owner_sequence_cannot_cross_time_or_chunk(change):
    with pytest.raises(ValueError, match="participation"):
        combat_events([p(0x3B), p(0x28) | change], {A})


def test_double_death_and_orphan_respawn_rejected():
    with pytest.raises(ValueError, match="Second death"):
        combat_events(kill_sequence() + kill_sequence(11), {A, B, C})
    with pytest.raises(ValueError, match="without"):
        combat_events([p(0x45E, size=13)], {A})


@pytest.mark.parametrize("opcode,size", [(0x28, 4), (0x45E, 12)])
def test_unknown_lifecycle_shape_rejected(opcode, size):
    with pytest.raises(ValueError, match="shape"):
        combat_events([p(opcode, size=size)], {A})


def test_keyframes_do_not_duplicate_death_events():
    kills, life = combat_events([p(0x28, stream=2)], {A})
    assert not kills and not life["events"]


def test_metadata_missing_is_not_zero_and_gold_is_not_subtracted():
    result = footer_categories([{"SKIN": "SyntheticHero", "TEAM": "100", "GOLD_EARNED": "2000", "GOLD_SPENT": "1200"}])
    assert result["economy"][0]["current_gold"] is None
    assert result["inventory"][0]["slots"][0]["item_id"] is None
    assert result["creep_score"][0]["lane_minions"] is None
    assert result["loadouts"][0]["temporal_scope"] == "final_metadata_only"
    assert number({"x": "0"}, "x") == 0


def test_null_shells_do_not_count_as_available_categories():
    categories = footer_categories([{"SKIN": "SyntheticHero", "TEAM": "100"}])
    categories.update(movement={"events": []}, levels=[], kills=[], lifecycle={"events": []})
    rows = category_coverage(categories)
    assert rows[0]["status"] == "available"
    assert all(r["status"] == "partial" and r["complete_record_count"] == 0 for r in rows[1:6])
    assert all(r["status"] == "no_events" for r in rows[6:])


@pytest.mark.parametrize("value", [True, "NaN", "Infinity", "-1", "abc"])
def test_invalid_numeric_metadata_rejected(value):
    with pytest.raises(ValueError):
        number({"x": value}, "x")


def test_future_events_and_footer_do_not_enter_prefix():
    kills, life = combat_events(kill_sequence() + [p(0x45E, A, 20, 13)], {A, B, C})
    bundle = {"identity_directory": {"owners": [{"entity_id": hex(i), "champion": None} for i in (A, B, C)]},
              "categories": {"kills": kills, "lifecycle": life, "levels": [
                  {"entity_id": hex(A), "packet_time_seconds": 18, "level_candidate": 5}],
                  "movement": {"events": []}, "inventory": [{"future_item": 9999}]}}
    s = state_at(bundle, 15)["entities"][0]
    assert s["life_state_candidate"] == "dead" and s["last_life_event_seconds"] == 10
    assert s["level_candidate"] is None and s["inventory"] is None
    assert "respawn_seconds" not in s
    assert s["deaths"] == 1
    assert state_at(bundle, 5)["entities"][0]["life_state_candidate"] == "unknown"
    assert state_at(bundle, 20)["entities"][0]["life_state_candidate"] == "alive_after_respawn_candidate"


@pytest.mark.parametrize("cutoff", [-1, float("nan"), float("inf"), True])
def test_invalid_cutoff_rejected(cutoff):
    with pytest.raises(ValueError):
        state_at({}, cutoff)


def test_replanning_does_not_mean_arrival_and_snapshot_stays_separate():
    def decoder(payload, inverse):
        return {"records": [{"entity_id": hex(A), "speed": 350,
            "relative_waypoints": [[0, 0], [2, 2]], "map_waypoints_assuming_legacy_origin": [[10, 10], [12, 12]],
            "flags": 4, "extra_byte": None, "decoded_offset": 0, "decoded_end": 20}]}
    result = movement_records([p(0xC9, stream=2), p(0xC9, time=11), p(0xC9, time=12)], {A}, decoder, b"")
    assert len(result["events"]) == 2 and len(result["snapshots"]) == 1
    assert result["plan_replacements"][0]["old_endpoint_arrived"] is None
    assert result["events"][0]["actual_arrival"] is None
