"""Synthetic pure-estimator tests; empirical replay errors are separate."""
from copy import deepcopy
import json
import math
from pathlib import Path

import pytest

from lol_coach.lane_tracking import estimate_path, latest_paths_at


def event(points=None, *, time=10., speed=10., stream=1, offset=1):
    return dict(entity_id='0x40000031', kind='path_command', time_seconds=time,
        relative_waypoints=[[0., 0.], [100., 0.]] if points is None else points,
        path_speed=speed, source=dict(stream=stream, chunk=1, decompressed_offset=offset,
                                     packet_index=offset))


def test_move_across_polyline_segments_without_corner_cutting():
    result = estimate_path(event([[0, 0], [100, 0], [100, 100]]), 25.)
    assert result['relative_position_estimate'] == [100., 50.]
    assert result['remaining_path_distance'] == 50.
    assert result['path_age_seconds'] == 15.
    assert result['coordinate_space'] == 'lane_relative'
    assert result['motion_state'] == 'moving_estimate'
    assert result['estimated'] and result['actual_arrival'] is None
    assert result['world_position_estimate'] is None


def test_repeated_waypoint_does_not_divide_by_zero():
    result = estimate_path(event([[0, 0], [0, 0], [100, 0]]), 11.)
    assert result['relative_position_estimate'] == [10., 0.]


@pytest.mark.parametrize('at', [20., 10000.])
def test_endpoint_clamps_but_does_not_assert_actual_arrival(at):
    result = estimate_path(event(), at)
    assert result['relative_position_estimate'] == [100., 0.]
    assert result['motion_state'] == 'planned_endpoint_estimate'
    assert result['endpoint_clamped'] is True
    assert result['remaining_path_distance'] == 0.
    assert result['actual_arrival'] is None and result['alive'] is None


def test_single_point_stops_and_replaces_previous_route():
    old = event()
    stop = event([[15, 0]], time=11.5, offset=2)
    latest = latest_paths_at([stop, old], 15.)
    result = estimate_path(latest[old['entity_id']], 15.)
    assert result['relative_position_estimate'] == [15, 0]
    assert result['motion_state'] == 'single_point_hold'
    assert result['endpoint_clamped'] is False
    assert result['source']['decompressed_offset'] == 2


def test_new_route_replaces_old_path_without_using_old_velocity():
    old = event()
    new = event([[20, 0], [20, 100]], time=12., offset=2)
    result = estimate_path(latest_paths_at([old, new], 13.)[old['entity_id']], 13.)
    assert result['relative_position_estimate'] == [20., 10.]


def test_same_timestamp_uses_packet_order():
    first = event(offset=10)
    second = event([[5, 5]], offset=20)
    assert latest_paths_at([second, first], 10.)[first['entity_id']] == second


def test_ambiguous_same_anchor_fails_closed():
    with pytest.raises(ValueError, match='Conflicting'):
        latest_paths_at([event(), event([[5, 5]])], 12.)


def test_future_and_checkpoint_paths_do_not_change_prefix():
    prior = event()
    future = event([[9999, 9999]], time=20.)
    checkpoint = event([[8888, 8888]], time=11., stream=2)
    assert latest_paths_at([future, checkpoint, prior], 12.) == latest_paths_at([prior], 12.)


def test_zero_speed_holds_first_point():
    result = estimate_path(event(speed=0), 15.)
    assert result['relative_position_estimate'] == [0., 0.]
    assert result['motion_state'] == 'zero_speed_hold'


def test_explicit_map_binding_translates_without_changing_relative_estimate():
    binding = dict(map_id=12, origin_xz=[6581, 6241], binding_status='inferred_profile')
    raw = event([[-1, 2]], speed=325.)
    before = deepcopy((raw, binding))
    result = estimate_path(raw, 15., map_binding=binding)
    assert result['relative_position_estimate'] == [-1, 2]
    assert result['world_position_estimate'] == [6580, 6243]
    assert (raw, binding) == before
    result['source']['chunk'] = 999
    assert raw['source']['chunk'] == 1


@pytest.mark.parametrize('binding', [{}, {'map_id': 12, 'origin_xz': [1, 2]},
    {'map_id': 99, 'origin_xz': [1, 2], 'binding_status': 'unknown'},
    {'map_id': 11, 'origin_xz': [math.nan, 0], 'binding_status': 'unknown'}])
def test_invalid_map_bindings_rejected(binding):
    with pytest.raises(ValueError):
        estimate_path(event(), 12., map_binding=binding)


@pytest.mark.parametrize('raw,at', [(event(stream=2), 12.), (event(), 9.),
    (event(), math.nan), (event(speed=-1), 12.), (event(speed=math.inf), 12.),
    (event([]), 12.), (event([[1, math.nan]]), 12.), (event([[1, 2, 3]]), 12.),
    (event(time=-1), 12.)])
def test_invalid_or_future_support_rejected(raw, at):
    with pytest.raises(ValueError):
        estimate_path(raw, at)


@pytest.mark.parametrize('name', ['Map11', 'Map12'])
def test_shipped_map_profile_is_explicit_estimated_translation(name):
    path = Path(__file__).parents[1]/'lol_coach/profiles/lane_tracking_16_20.json'
    profile = json.loads(path.read_text(encoding='utf-8'))
    assert profile['version'] == '16.20.824.8524'
    binding = profile['maps'][name]
    result = estimate_path(event([[0, 0]]), 12., map_binding=binding)
    assert result['world_position_estimate'] == binding['origin_xz']
    assert result['estimated'] is True
    assert binding['runtime_map_id_decoded'] is False
    assert profile['evaluation']['error_bounds_guaranteed'] is False
