"""Synthetic causal checks; these are not observed in-game timing trials."""
from copy import deepcopy

import pytest

from lol_coach.travel_validity import TravelValidityTracker, query_validity


BINDING = dict(source_sha256="a" * 64, version="16.20.824.8524", observer_team_id=100)


def event(kind, *, at=0.0, offset=1, actor="unit", stream=1, **payload):
    return dict(kind=kind, entity_id=actor, time_seconds=at,
                source_sha256=BINDING["source_sha256"], version=BINDING["version"],
                source=dict(stream=stream, chunk=1, decompressed_offset=offset,
                            packet_index=0, ordinal=0), **payload)


def visible(**kwargs):
    kwargs.setdefault("value", True)
    kwargs.setdefault("observer_team_id", 100)
    return event("visibility", **kwargs)


def health(**kwargs):
    kwargs.setdefault("value", 100)
    kwargs.setdefault("offset", 2)
    return event("health", **kwargs)


def path(**kwargs):
    kwargs.setdefault("points", [[0, 0], [400, 0]])
    kwargs.setdefault("speed", 100)
    kwargs.setdefault("offset", 3)
    kwargs.setdefault("entity_team_id", 100)
    return event("path", **kwargs)


def start():
    return [visible(), health(), path()]


def query(events, at=0.5, **overrides):
    return query_validity(events, at_seconds=at, **dict(BINDING, **overrides))


def unit(events, at=0.5, **overrides):
    return query(events, at, **overrides)["entities"]["unit"]


def assert_no_arrival(row):
    assert row["actual_arrival_seconds"] is None
    assert row["decision_input_eligible"] is False
    if row["arrival_observation"] is not None:
        assert row["arrival_observation"]["exact_arrival_seconds"] is None


def test_visible_alive_polyline_has_conditional_time_only():
    events = [visible(), health(), path(points=[[0, 0], [100, 0], [100, 100]])]
    report = query(events, at=0.25)
    row = report["entities"]["unit"]
    assert report["schema"] == "travel-validity/v1"
    assert report["binding"] == BINDING
    assert report["max_path_age_seconds"] == 1.0
    assert report["decision_input_eligible"] is False
    assert row["status"] == "conditional_active"
    assert row["conditional_remaining_seconds"] == pytest.approx(1.75)
    assert row["plan"]["path_length"] == 200
    assert row["plan"]["expires_at_seconds"] == 1.0
    assert_no_arrival(row)


def test_missing_visibility_does_not_create_hidden_identity_or_eta():
    assert query([health(), path()])["entities"] == {}


def test_missing_health_never_activates_a_visible_route():
    row = unit([visible(), path()])
    assert row["status"] == "unknown_liveness"
    assert row["conditional_remaining_seconds"] is None
    assert_no_arrival(row)


@pytest.mark.parametrize("team", [None, 200, 300, True, 100.0, "100"])
def test_visible_enemy_or_unverified_ownership_cannot_supply_planned_route(team):
    with pytest.raises(ValueError, match="ownership"):
        query([visible(), health(), path(entity_team_id=team)])


def test_observer_200_accepts_its_own_route_only():
    events = [visible(observer_team_id=200), health(), path(entity_team_id=200)]
    report = query(events, observer_team_id=200)
    assert report["entities"]["unit"]["status"] == "conditional_active"
    assert report["binding"]["observer_team_id"] == 200
    with pytest.raises(ValueError, match="ownership"):
        query([visible(observer_team_id=200), health(), path()], observer_team_id=200)


def test_visible_enemy_position_report_does_not_reveal_a_planned_route():
    events = [visible(), health(), event("position", offset=3, point=[50, 50], entity_team_id=200)]
    row = unit(events)
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    assert_no_arrival(row)


def test_positive_health_can_establish_liveness_without_death_history():
    events = [visible(), path(), health(at=0.2, offset=4)]
    assert unit(events)["conditional_remaining_seconds"] == pytest.approx(3.5)


def test_future_events_and_checkpoint_payloads_cannot_change_prefix():
    base = start()
    pollution = [path(at=0.6, points=[[999, 999], [0, 0]], speed=999),
                 event("death", at=1.0, public=True),
                 visible(at=0.1, value=False, stream=2),
                 health(at=0.1, value=0, stream=2),
                 path(at=0.1, speed=999, stream=2)]
    pollution[0]["version"] = "future-build-not-current"
    assert query(base + pollution) == query(base)


def test_foreign_observer_visibility_does_not_hide_or_reveal_units():
    ignored = visible(at=0.2, value=False, observer_team_id=200)
    assert query(start() + [ignored]) == query(start())
    events = [visible(observer_team_id=200), health(), path()]
    assert query(events)["entities"] == {}


def test_foreign_observer_same_packet_cannot_conflict_with_local_visibility():
    foreign = visible(observer_team_id=200, value=False)
    assert query([foreign, *start()]) == query(start())
    assert query([*start(), foreign]) == query(start())


def test_hidden_samples_do_not_reintroduce_position_health_speed_or_path():
    prefix = start() + [visible(at=0.1, value=False)]
    hidden = [health(at=0.2), path(at=0.25),
              event("speed", at=0.3, value=120),
              event("position", at=0.4, point=[400, 0]),
              event("respawn_candidate", at=0.45)]
    assert query(prefix + hidden) == query(prefix)


@pytest.mark.parametrize("visibility", [False, None])
def test_reentry_requires_positive_health_and_a_fresh_path(visibility):
    lost = visible(at=0.1, value=visibility)
    reentry = visible(at=0.2)
    events = start() + [lost, reentry]
    row = unit(events)
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    assert row["status"] == "unknown_liveness"
    events.append(health(at=0.3))
    row = unit(events)
    assert row["status"] == "awaiting_new_path"
    assert row["conditional_remaining_seconds"] is None
    events.append(path(at=0.4))
    assert unit(events)["conditional_remaining_seconds"] == pytest.approx(3.9)


def test_repeated_visibility_true_does_not_reset_fresh_plan():
    assert query(start() + [visible(at=0.2)]) == query(start())


@pytest.mark.parametrize("terminal", [event("death", at=0.1), health(at=0.1, value=0)])
def test_death_clears_route_and_positive_health_does_not_restore_it(terminal):
    events = start() + [terminal, path(at=0.2)]
    row = unit(events)
    assert row["status"] == "blocked_dead"
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    events.append(health(at=0.3))
    row = unit(events)
    assert row["status"] == "awaiting_new_path"
    assert row["plan"] is None
    events.append(path(at=0.4))
    assert unit(events)["status"] == "conditional_active"


def test_respawn_candidate_does_not_prove_alive_or_revive_predeath_plan():
    events = start() + [event("death", at=0.1), event("respawn_candidate", at=0.2)]
    row = unit(events)
    assert row["status"] == "unknown_liveness"
    assert row["plan"] is None
    events.append(path(at=0.3))
    assert unit(events)["conditional_remaining_seconds"] is None
    events.append(health(at=0.4))
    assert unit(events)["conditional_remaining_seconds"] == pytest.approx(3.8)


def test_hidden_public_death_clears_known_plan_but_reentry_still_needs_health():
    events = start() + [visible(at=0.1, value=False),
                        event("death", at=0.2, public=True), visible(at=0.3)]
    row = unit(events)
    assert row["status"] == "blocked_dead"
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None


def test_removal_candidate_is_terminal_without_claiming_exact_death():
    events = start() + [event("removal_candidate", at=0.2, entity_kind="minion")]
    row = unit(events)
    assert row["status"] == "terminal_candidate"
    assert row["terminal_candidate"] is True
    assert row["alive"] is None
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    assert_no_arrival(row)


@pytest.mark.parametrize("terminal", [event("death", at=0.1, entity_kind="minion"),
                                      health(at=0.1, value=0, entity_kind="minion")])
def test_terminal_minion_cannot_be_revived_by_late_health_or_respawn(terminal):
    events = start() + [terminal, health(at=0.2, entity_kind="minion"),
                        event("respawn_candidate", at=0.3, entity_kind="minion"),
                        path(at=0.4, entity_kind="minion")]
    row = unit(events)
    assert row["status"] == "blocked_dead"
    assert row["alive"] is False
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    assert_no_arrival(row)


def test_removal_candidate_survives_visibility_reentry_and_fresh_samples():
    events = start() + [event("removal_candidate", at=0.1, entity_kind="minion"),
                        visible(at=0.2, value=False), visible(at=0.3),
                        health(at=0.4, entity_kind="minion"),
                        path(at=0.45, entity_kind="minion")]
    row = unit(events)
    assert row["status"] == "terminal_candidate"
    assert row["alive"] is None
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None


def test_zero_health_minion_stays_dead_after_visibility_reentry():
    events = start() + [health(at=0.1, value=0, entity_kind="minion"),
                        visible(at=0.2, value=None), visible(at=0.3),
                        health(at=0.4, entity_kind="minion"),
                        path(at=0.45, entity_kind="minion")]
    row = unit(events)
    assert row["status"] == "blocked_dead"
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None


def test_new_path_replaces_start_and_duration_with_traceable_transition():
    original = unit(start())["plan"]
    new = path(at=0.2, points=[[20, 0], [70, 0]], speed=50)
    row = unit(start() + [new])
    assert row["plan"]["plan_id"] != original["plan_id"]
    assert row["plan"]["points"] == [[20, 0], [70, 0]]
    assert row["conditional_remaining_seconds"] == pytest.approx(0.7)
    assert row["last_transition"]["invalidated_plan_id"] == original["plan_id"]
    assert row["last_transition"]["source"] == new["source"]


@pytest.mark.parametrize("value", [0, 200])
def test_speed_change_invalidates_instead_of_recomputing_from_old_position(value):
    changed = event("speed", at=0.2, value=value)
    events = start() + [changed]
    row = unit(events)
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    assert row["last_transition"]["reason"] == "speed_changed_requires_new_path"
    events.append(event("position", at=0.3, point=[30, 0]))
    assert unit(events)["plan"] is None
    assert unit(events)["conditional_remaining_seconds"] is None


def test_same_speed_preserves_plan_but_does_not_refresh_route_age():
    events = start() + [event("speed", at=0.8, value=100)]
    row = unit(events, at=1)
    assert row["status"] == "observation_stale"
    assert row["conditional_remaining_seconds"] is None
    assert row["plan"]["issued_at_seconds"] == 0


@pytest.mark.parametrize("at, status", [(0.999, "conditional_active"),
                                       (1.0, "observation_stale"),
                                       (3.999, "observation_stale"),
                                       (4.0, "due_unconfirmed"),
                                       (10.0, "due_unconfirmed")])
def test_age_and_nominal_arrival_have_explicit_nonarrival_statuses(at, status):
    row = unit(start(), at=at)
    assert row["status"] == status
    if status != "conditional_active":
        assert row["conditional_remaining_seconds"] is None
    assert_no_arrival(row)


def test_custom_age_is_recorded_and_never_extends_past_nominal_arrival():
    report = query(start(), at=3.5, max_path_age_seconds=10)
    assert report["max_path_age_seconds"] == 10
    assert report["entities"]["unit"]["conditional_remaining_seconds"] == pytest.approx(0.5)
    assert report["entities"]["unit"]["plan"]["expires_at_seconds"] == 4
    row = unit(start(), at=4, max_path_age_seconds=10)
    assert row["status"] == "due_unconfirmed"
    assert row["conditional_remaining_seconds"] is None


@pytest.mark.parametrize("points,speed", [([[50, 0]], 100),
                                         ([[0, 0], [0, 0]], 100),
                                         ([[0, 0], [100, 0]], 0)])
def test_stop_zero_length_and_zero_speed_do_not_mean_arrival(points, speed):
    row = unit(start() + [path(at=0.2, points=points, speed=speed)])
    assert row["plan"] is None
    assert row["conditional_remaining_seconds"] is None
    assert row["arrival_observation"] is None
    assert_no_arrival(row)


def test_position_refresh_does_not_extend_plan_or_establish_movement_intent():
    events = start() + [event("position", at=0.8, point=[80, 0])]
    row = unit(events, at=1.1)
    assert row["status"] == "observation_stale"
    assert row["conditional_remaining_seconds"] is None
    assert row["arrival_observation"] is None


@pytest.mark.parametrize("kind", ["position", "path"])
def test_endpoint_report_keeps_arrival_unknown(kind):
    endpoint = event(kind, at=0.5, point=[400, 0]) if kind == "position" else path(at=0.5, points=[[400, 0]])
    row = unit(start() + [endpoint])
    report = row["arrival_observation"]
    assert report["observed_at_seconds"] == 0.5
    assert report["report_position"] == [400, 0]
    assert report["source"] == endpoint["source"]
    assert_no_arrival(row)


def test_same_timestamp_uses_packet_and_ordinal_order_not_list_order():
    first = path(points=[[0, 0], [100, 0]])
    second = path(points=[[0, 0], [200, 0]])
    second["source"]["packet_index"] = 1
    stop = path(points=[[20, 0]])
    stop["source"].update(packet_index=1, ordinal=1)
    prefix = [visible(), health()]
    assert unit(prefix + [second, first])["plan"]["points"] == second["points"]
    assert unit(prefix + [stop, second, first])["plan"] is None


def test_same_timestamp_death_after_path_blocks_immediately():
    dead = event("death", offset=4)
    row = unit([dead, *start()], at=0)
    assert row["status"] == "blocked_dead"
    assert row["plan"] is None


def test_conflicting_events_without_distinguishable_source_order_are_rejected():
    a = path()
    b = path(points=[[0, 0], [999, 999]])
    with pytest.raises(ValueError):
        query([visible(), health(), a, b])


def test_identical_duplicate_events_are_idempotent():
    events = start()
    assert query([events[0], events[1], events[2], deepcopy(events[2])]) == query(events)


def test_distinct_entities_in_same_packet_do_not_conflict():
    first = start()
    second = deepcopy(first)
    for item in second:
        item["entity_id"] = "another_unit"
    report = query(first + second)
    assert set(report["entities"]) == {"unit", "another_unit"}
    for row in report["entities"].values():
        assert row["conditional_remaining_seconds"] == pytest.approx(3.5)


def test_exact_cutoff_includes_current_event_and_excludes_later_death():
    events = [visible(), health(), path(at=0.5), event("death", at=0.50001)]
    at_cutoff = unit(events, at=0.5)
    assert at_cutoff["conditional_remaining_seconds"] == 4
    assert unit(events, at=0.50001)["status"] == "blocked_dead"


def test_batch_and_incremental_prefix_queries_agree_at_every_cutoff():
    events = start() + [event("speed", at=0.5, value=200),
                        path(at=0.75, points=[[75, 0], [475, 0]], speed=200),
                        visible(at=1, value=False), path(at=1.1),
                        visible(at=1.5), health(at=1.6), path(at=1.7)]
    tracker = TravelValidityTracker(**BINDING)
    cursor = 0
    for at in (0, 0.25, 0.5, 0.75, 1, 1.25, 1.5, 1.75, 2.75, 10):
        while cursor < len(events) and events[cursor]["time_seconds"] <= at:
            tracker.feed(events[cursor])
            cursor += 1
        assert tracker.snapshot(at) == query(list(reversed(events)), at)


def test_snapshot_before_fed_data_and_out_of_order_feed_are_rejected():
    tracker = TravelValidityTracker(**BINDING)
    tracker.feed(visible(at=2))
    with pytest.raises(ValueError):
        tracker.snapshot(1)
    with pytest.raises(ValueError):
        tracker.feed(health(at=1))


def test_snapshot_and_input_mutations_do_not_modify_tracker():
    tracker = TravelValidityTracker(**BINDING)
    events = start()
    original = deepcopy(events)
    for item in events:
        tracker.feed(item)
    before = tracker.snapshot(0.5)
    assert events == original
    events[-1]["points"][0][0] = 999
    events[-1]["source"]["chunk"] = 999
    mutated = tracker.snapshot(0.5)
    mutated["entities"]["unit"]["plan"]["points"][0][0] = -999
    mutated["binding"]["version"] = "changed"
    assert tracker.snapshot(0.5) == before


@pytest.mark.parametrize("field,value", [("source_sha256", "b" * 64), ("version", "other")])
def test_live_binding_mismatch_is_rejected(field, value):
    bad = path()
    bad[field] = value
    with pytest.raises(ValueError):
        query([visible(), health(), bad])


@pytest.mark.parametrize("kwargs", [dict(source_sha256="bad"), dict(version="other"),
                                     dict(observer_team_id=True), dict(observer_team_id=300),
                                     dict(max_path_age_seconds=0), dict(max_path_age_seconds=-1),
                                     dict(max_path_age_seconds=True), dict(max_path_age_seconds=float("nan")),
                                     dict(max_path_age_seconds=float("inf"))])
def test_invalid_constructor_binding_or_age_is_rejected(kwargs):
    with pytest.raises(ValueError):
        TravelValidityTracker(**dict(BINDING, **kwargs))


@pytest.mark.parametrize("value", [-1, True, float("inf"), float("nan"), "1"])
def test_invalid_cutoffs_rejected(value):
    with pytest.raises(ValueError):
        query(start(), at=value)


@pytest.mark.parametrize("bad", [health(value=-1), health(value=True),
                                 event("speed", offset=4, value=float("nan")),
                                 event("speed", offset=4, value=-1),
                                 path(speed=float("inf")), path(speed=True),
                                 path(points=[[0, 0], [float("nan"), 0]]),
                                 path(points=[[0, 0], [True, 0]]),
                                 path(points=[]), visible(value=1),
                                 event("position", offset=4, point=[1, 2, 3])])
def test_invalid_observed_values_are_rejected(bad):
    bad = deepcopy(bad)
    bad["time_seconds"] = 0.2
    with pytest.raises(ValueError):
        query(start() + [bad])


@pytest.mark.parametrize("value", [-1, True, float("nan"), float("inf")])
def test_invalid_live_timestamps_rejected(value):
    bad = path(at=value)
    with pytest.raises(ValueError):
        query(start() + [bad])


@pytest.mark.parametrize("value", [True, -2, 0.5, "1"])
def test_invalid_source_order_rejected(value):
    bad = path()
    bad["source"]["decompressed_offset"] = value
    with pytest.raises(ValueError):
        query([visible(), health(), bad])
