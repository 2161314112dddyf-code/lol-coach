"""Synthetic observer/model-admission contracts, not gameplay validation."""
from copy import deepcopy
import json

import pytest

import lol_coach.lane_wave as wave


SHA = 'a' * 64
VERSION = '16.20.824.8524'


def source(at, stream=1):
    return dict(stream=stream, chunk=1, decompressed_offset=int(at*100))


def identity(actor='a', team=100, kind='melee', lane='middle', at=1):
    return dict(entity_id=actor, time_seconds=at, source=source(at),
                identity=dict(team_id=team, lane=lane, kind=kind))


def event(at, kind, actor='a', stream=1, **extra):
    return dict(entity_id=actor, time_seconds=at, source=source(at, stream), kind=kind, **extra)


def vis(at=2, actor='a', visible=True, team=100, **extra):
    kind = 'visibility_unknown_barrier' if visible is None else 'visibility_enter' if visible else 'visibility_leave'
    return event(at, kind, actor, observer_team_id=team, visible=visible, **extra)


def hp(at=3, actor='a', health=100, maximum=400, **extra):
    values = {}
    if health is not None:
        values['health'] = health
    if maximum is not None:
        values['max_health'] = maximum
    return event(at, 'health_sample', actor, values=values, fields={}, **extra)


def path(at=4, actor='a', points=None, speed=100, **extra):
    return event(at, 'path_command', actor,
                 relative_waypoints=points if points is not None else [[0, 0]], path_speed=speed, **extra)


def bundle(events=None, identities=None):
    return dict(schema='lane-dynamics-evidence/v1', version=VERSION,
        source={'sha256': SHA, 'fixture': 'synthetic'}, recording_end_seconds=100,
        identities=[identity()] if identities is None else identities,
        events=[vis(), hp(), path()] if events is None else events)


def view(data=None, at=10, towers=None):
    return wave.build_lane_view(data or bundle(), at=at, team=100, source_sha256=SHA, towers=towers)


def admitted(data=None, at=10, towers=None):
    return wave.model_view(view(data, at, towers), at=at, team=100)


def units(model):
    return [u for lane in model['lanes'] for group in lane['spatial_groups'] for u in group['units']] + [
        u for lane in model['lanes'] for u in lane['unlocated_units']]


@pytest.fixture
def anchors(monkeypatch, tmp_path):
    p = tmp_path/'synthetic-tracking-profile.json'
    p.write_text(json.dumps(dict(version=VERSION, data_kind='synthetic', maps={
        'Map12': dict(map_id=12, origin_xz=[1000, 2000], binding_status='synthetic_fixture')},
        evaluation=dict(checkpoint_comparison=dict(advance_along_path=dict(
            count=4, median=1.0, p90=3.0, maximum=4.0))))))
    monkeypatch.setattr(wave, 'PROFILE', p)
    return dict(schema='turret-state/v1', version=VERSION, source={'sha256': SHA}, identity_events=[
        dict(entity_id='tower', time_seconds=1, source=source(1), identity=dict(team=200,
            name='synthetic tower', role='outer', map_reference='Map12', map_reference_position=[1100, 0, 2000]))])


def test_visible_health_retained_and_current_position_is_explicit_estimate():
    model = admitted(bundle([vis(), hp(), path(points=[[0, 0], [1000, 0]])]))
    unit = units(model)[0]
    assert model['known_visible_alive_count'] == 1
    assert unit['health'] == 100 and unit['max_health'] == 400
    assert unit['health_updated_at_seconds'] == 3
    assert unit['health_age_seconds'] == 7
    assert unit['position']['relative_xz'] == [600, 0]
    assert unit['position']['world_xz'] is None
    assert unit['position']['motion'] == 'moving_estimate'
    assert unit['position']['endpoint_clamped'] is False
    assert 'unknown_delivery_delay' in unit['health_semantics']
    assert 'not_direct_position_or_proven_arrival' in unit['position']['semantics']


def test_single_point_and_clamped_endpoints_never_claim_arrival():
    for points, clamped in [([[7, 8]], False), ([[0, 0], [10, 0]], True)]:
        unit = units(admitted(bundle([vis(), hp(), path(points=points)])))[0]
        assert unit['position']['endpoint_clamped'] is clamped
        assert 'not_direct_position_or_proven_arrival' in unit['position']['semantics']
        assert 'actual_arrival' not in unit['position']


@pytest.mark.parametrize('kind', ['zero', 'terminal_removal_candidate'])
def test_terminal_entities_are_excluded_even_after_path_or_visibility(kind):
    death = hp(5, health=0) if kind == 'zero' else event(5, kind)
    model = admitted(bundle([vis(), hp(), path(), death, path(6), vis(7)]))
    assert model['known_visible_alive_count'] == 0
    assert model['observed_terminal_entities_count'] == 1
    assert model['lanes'] == []


@pytest.mark.parametrize('state', [False, None])
def test_hidden_unknown_fields_and_lifecycle_do_not_change_model_view(state):
    data = bundle([vis(), hp(), path(), vis(5, visible=state), hp(6, health=0),
                   path(7, points=[[9999, 8888]]), event(8, 'terminal_removal_candidate')])
    changed = deepcopy(data)
    changed['events'][4]['values'] = {'health': 123456}
    changed['events'][5]['relative_waypoints'] = [[-12345, -67890]]
    changed['events'][6]['payload_hex'] = 'hidden_secret'
    assert admitted(data) == admitted(changed)
    model = admitted(data)
    assert model['known_visible_alive_count'] == 0
    assert model['previously_seen_currently_unresolved_count'] == 1
    assert model['observed_terminal_entities_count'] == 0


def test_future_and_checkpoint_fields_do_not_change_model_view():
    data = bundle([vis(), hp(), path(), hp(80, health=0), path(80, points=[[999, 999]]),
                   hp(5, health=0, stream=2), path(6, stream=2, points=[[999, 999]]),
                   event(7, 'terminal_removal_candidate', stream=2)])
    changed = deepcopy(data)
    for row in changed['events'][3:]:
        row['values'] = {'health': 999999}
        row['relative_waypoints'] = [[123456, 123456]]
    changed['identities'].append(identity('future', at=80))
    assert admitted(data) == admitted(changed)
    assert admitted(data)['known_visible_alive_count'] == 1


def test_reentry_requires_new_interval_path_and_health():
    data = bundle([vis(), hp(), path(), vis(5, visible=False), hp(6, health=90),
                   path(7, points=[[9999, 8888]]), vis(8)])
    unit = units(admitted(data))[0]
    assert unit['position'] is None
    assert unit['health'] is None
    assert admitted(data)['lanes'][0]['position_estimated_count'] == 0
    assert admitted(data)['lanes'][0]['health_known_count'] == 0


def test_radius_connected_components_are_not_spawn_wave_or_combat_evidence():
    identities = [identity('a'), identity('b', kind='ranged'), identity('c', team=200)]
    events = [r for a, x in [('a', 0), ('b', 500), ('c', 1000)]
              for r in (vis(actor=a), hp(actor=a), path(actor=a, points=[[x, 0]]))]
    model = admitted(bundle(events, identities))
    assert model['grouping_rule']['method'] == 'radius_connected_components'
    assert model['grouping_rule']['radius_units'] == 600
    assert model['grouping_rule']['is_decoded_spawn_wave_id'] is False
    lane = model['lanes'][0]
    assert lane['known_visible_alive_count'] == 3
    assert lane['complete_lane_count'] is None and lane['lane_priority'] is None
    assert len(lane['spatial_groups']) == 1
    group = lane['spatial_groups'][0]
    assert len(group['units']) == 3
    assert group['both_teams_present'] is True
    assert group['contact'] == 'opposing_units_nearby_not_proof_of_attacks'
    assert 'spatial' in group['group_id']
    assert 'combat' not in group and 'wave_id' not in group


def test_single_team_group_does_not_claim_pressure_or_tower_arrival():
    model = admitted()
    group = model['lanes'][0]['spatial_groups'][0]
    assert group['both_teams_present'] is False
    assert group['contact'] == 'single_team_group'
    assert model['lanes'][0]['lane_priority'] is None
    assert 'arrival_eta' not in group


def test_unknown_health_does_not_disappear_from_counts_or_become_zero():
    model = admitted(bundle([vis(), path()]))
    lane = model['lanes'][0]
    assert lane['known_visible_alive_count'] == 1
    assert lane['health_known_count'] == 0
    assert units(model)[0]['health'] is None
    assert units(model)[0]['max_health'] is None


def test_source_and_build_mismatch_rejected():
    data = bundle()
    data['source']['sha256'] = 'b'*64
    with pytest.raises(ValueError):
        view(data)
    data = bundle()
    data['version'] = '16.21'
    with pytest.raises(ValueError):
        view(data)
    with pytest.raises(ValueError):
        wave.build_lane_view(bundle(), at=10, team=None, source_sha256=SHA)


def test_static_tower_binding_is_provenance_checked_and_not_alive_or_in_range(anchors):
    model = admitted(towers=anchors)
    unit = units(model)[0]
    assert unit['position']['world_xz'] == [1000, 2000]
    group = model['lanes'][0]['spatial_groups'][0]
    assert group['nearest_static_tower']['entity_id'] == 'tower'
    assert group['nearest_static_tower']['distance_units_estimate'] == 100
    assert 'not_tower_alive_or_in_range' in group['nearest_static_tower']['semantics']
    for key, value in [('version', 'wrong'), ('source', {'sha256': 'b'*64})]:
        wrong = deepcopy(anchors)
        wrong[key] = value
        with pytest.raises(ValueError):
            admitted(towers=wrong)


def test_future_tower_identity_cannot_authorize_world_binding(anchors):
    anchors['identity_events'][0]['time_seconds'] = 80
    model = admitted(towers=anchors)
    assert units(model)[0]['position']['world_xz'] is None
    assert model['coordinate_basis']['map_reference'] is None


def test_checkpoint_only_tower_identity_cannot_authorize_world_binding(anchors):
    anchors['identity_events'][0]['source']['stream'] = 2
    model = admitted(towers=anchors)
    assert units(model)[0]['position']['world_xz'] is None
    assert model['coordinate_basis']['map_reference'] is None


def test_time_zero_checkpoint_may_bind_named_static_geometry_not_dynamic_state(anchors):
    record = anchors['identity_events'][0]
    record['time_seconds'] = 0
    record['source'] = source(0, stream=2)
    record['identity']['current_position'] = [999999, 999999]
    record['identity']['current_health'] = 'CHECKPOINT_DYNAMIC_SECRET'
    anchors['events'] = [{'time_seconds': 0, 'health': 'CHECKPOINT_DYNAMIC_SECRET'}]
    original = deepcopy(anchors)
    model = admitted(towers=anchors)
    assert units(model)[0]['position']['world_xz'] == [1000, 2000]
    assert model['lanes'][0]['spatial_groups'][0]['nearest_static_tower']['distance_units_estimate'] == 100
    assert 'CHECKPOINT_DYNAMIC_SECRET' not in json.dumps(model)
    assert anchors == original


def test_nested_sentinels_and_audit_are_not_admitted_to_model(anchors):
    data = bundle([vis(), hp(), path(), vis(actor='b')],
                  [identity(), identity('b', team=200)])
    original = view(data, towers=anchors)
    expected = wave.model_view(original, at=10, team=100)
    dirty = deepcopy(original)
    sentinel = 'RAW_HIDDEN_FUTURE_PAYLOAD_SENTINEL'
    def poison(value):
        if isinstance(value, dict):
            for child in list(value.values()):
                poison(child)
            value['untrusted_raw_extra'] = sentinel
        elif isinstance(value, list):
            for child in value:
                poison(child)
    poison(dirty['model'])
    dirty['audit'] = {'raw_replay': sentinel}
    dirty['extra_raw'] = sentinel
    clean = wave.model_view(dirty, at=10, team=100)
    assert sentinel not in json.dumps(clean)
    assert clean == expected
    assert 'audit' not in clean and 'source_sha256' not in clean


@pytest.mark.parametrize('field', ['top_count', 'lane_counts', 'group_counts', 'health_count', 'position_count'])
def test_model_admission_rejects_inconsistent_counts(field):
    dirty = view()
    lane = dirty['model']['lanes'][0]
    if field == 'top_count':
        dirty['model']['known_visible_alive_count'] = 9999
    elif field == 'lane_counts':
        lane['counts'][0]['count'] = 9999
    elif field == 'group_counts':
        lane['spatial_groups'][0]['counts'][0]['count'] = 9999
    elif field == 'health_count':
        lane['health_known_count'] = 9999
    else:
        lane['position_estimated_count'] = 9999
    with pytest.raises(ValueError):
        wave.model_view(dirty, at=10, team=100)


def test_model_admission_rejects_duplicate_entity_across_lanes():
    dirty = view()
    duplicate = deepcopy(dirty['model']['lanes'][0])
    duplicate['lane'] = 'top'
    dirty['model']['lanes'].append(duplicate)
    dirty['model']['known_visible_alive_count'] = 2
    with pytest.raises(ValueError):
        wave.model_view(dirty, at=10, team=100)


@pytest.mark.parametrize('field', ['health_updated_at_seconds', 'path_updated_at_seconds'])
def test_model_admission_rejects_future_sample_timestamps(field):
    dirty = view()
    unit = units(dirty['model'])[0]
    if field.startswith('health'):
        unit[field] = 11
    else:
        unit['position'][field] = 11
    with pytest.raises(ValueError):
        wave.model_view(dirty, at=10, team=100)


def test_context_and_unqualified_views_are_rejected_and_input_not_mutated():
    data = bundle()
    before = deepcopy(data)
    result = view(data)
    assert before == data
    with pytest.raises(ValueError):
        wave.model_view(result, at=11, team=100)
    with pytest.raises(ValueError):
        wave.model_view(result, at=10, team=200)
    result['model_input_eligible'] = False
    with pytest.raises(ValueError):
        wave.model_view(result, at=10, team=100)
