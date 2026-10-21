"""Synthetic fixtures: safeguards, not gameplay validation."""
import math
import pytest
from lol_coach.movement_validation import candidate_transitions, shared_clock_offset, observed_duration_interval


def record(t, points, speed=10):
    return {'time': t, 'points': points, 'speed': speed}


def test_planned_endpoint_does_not_establish_actual_arrival():
    out = candidate_transitions([record(1, [[0, 0], [30, 40]]), record(6, [[30, 40]])])[0]
    assert out['kind'] == 'single_point_at_planned_endpoint'
    assert out['constant_speed_duration_hypothesis_seconds'] == 5
    assert out['actual_duration_seconds'] is None and out['actual_arrival'] is None


def test_stop_short_does_not_become_endpoint_or_manual_input():
    out = candidate_transitions([record(1, [[0, 0], [100, 0]]), record(3, [[20, 0]])])[0]
    assert out['kind'] == 'single_point_elsewhere'
    assert out['manual_stop_confirmed'] is None


def test_replan_does_not_count_old_destination_as_reached():
    out = candidate_transitions([record(1, [[0, 0], [100, 0]]), record(2, [[10, 0], [20, 0]]), record(3, [[20, 0]])])
    assert [r['kind'] for r in out] == ['path_superseded', 'single_point_at_planned_endpoint']
    assert out[1]['planned_length_game_units'] == 10


def test_zero_speed_keeps_duration_unknown():
    out = candidate_transitions([record(1, [[0, 0], [10, 0]], 0), record(3, [[10, 0]])])[0]
    assert out['constant_speed_duration_hypothesis_seconds'] is None


@pytest.mark.parametrize('records', [
    [record(2, [[0, 0]]), record(1, [[0, 0]])],
    [record(1, [[math.nan, 0]])],
    [record(1, [])],
])
def test_invalid_records_rejected(records):
    with pytest.raises(ValueError):
        candidate_transitions(records)


def test_unfinished_path_has_no_arrival():
    out = candidate_transitions([record(1, [[0, 0], [10, 0]])])
    assert out == [{'kind': 'open_path', 'start_time': 1, 'actual_arrival': None}]


def test_clock_mismatch_not_silently_fitted():
    out = shared_clock_offset([
        {'packet_time_seconds': 5, 'video_interval_seconds': [1, 2]},
        {'packet_time_seconds': 10, 'video_interval_seconds': [8, 9]},
    ])
    assert not out['has_shared_offset']
    assert out['shared_offset_interval_seconds'] is None
    assert out['minimum_interval_gap_seconds'] == 1


def test_clock_overlap_retains_interval():
    out = shared_clock_offset([
        {'packet_time_seconds': 5, 'video_interval_seconds': [1, 2]},
        {'packet_time_seconds': 10, 'video_interval_seconds': [6, 7]},
    ])
    assert out['shared_offset_interval_seconds'] == [3, 4]


def test_observed_duration_propagates_both_uncertainties():
    assert observed_duration_interval([10, 11], [15, 17]) == [4, 7]


@pytest.mark.parametrize('start,end', [
    ([1, 3], [2, 4]), ([1, 2], [2, 4]),
    ([2, 1], [4, 5]), ([1, math.nan], [4, 5]),
    ([True, 2], [4, 5]), ([-1, 0], [4, 5]),
])
def test_ambiguous_or_invalid_observation_not_turned_into_duration(start, end):
    with pytest.raises(ValueError):
        observed_duration_interval(start, end)
