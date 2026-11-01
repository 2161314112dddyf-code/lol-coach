"""Synthetic end-to-end lane evidence to model-input boundary checks.

These exercise integration and information filtering, not tactical accuracy.
No private replay or network access is required.
"""
from copy import deepcopy
import json

import pytest

from lol_coach.analysis_context import build_context
from lol_coach.reasoning_frame import compile_frame, model_messages
from test_analysis_integration import make_cache
from test_lane_current_state import bundle, hp, identity, row, vis
from test_macro_snapshot import bundles


def lane_fixture():
    data = bundle([
        vis(2, actor='lane-a'), vis(2, actor='lane-b'), vis(2, actor='lane-hidden'),
        hp(3, 300, 400, actor='lane-a'), hp(3, 350, 400, actor='lane-b'),
        hp(3, 250, 400, actor='lane-hidden'),
        row(4, 'path_command', 'lane-a', relative_waypoints=[[0, 0], [12345, 0]], path_speed=10.),
        row(4, 'path_command', 'lane-b', relative_waypoints=[[100, 0], [12345, 0]], path_speed=10.),
        row(4, 'path_command', 'lane-hidden', relative_waypoints=[[500, 0], [12345, 0]], path_speed=10.),
        vis(5, False, actor='lane-hidden'), hp(6, 220, actor='lane-a'),
        hp(6, 7777, actor='lane-hidden'),
        row(7, 'path_command', 'lane-hidden', relative_waypoints=[[9999, 9999], [12345, 0]], path_speed=10.),
        hp(7, 8888, actor='lane-a', stream=2),
        row(7, 'path_command', 'lane-a', stream=2, relative_waypoints=[[8888, 8888]], path_speed=10.),
        hp(10, 9999, actor='lane-a'),
        row(10, 'path_command', 'lane-a', relative_waypoints=[[7777, 7777]], path_speed=10.),
    ], identities=[identity('lane-a'), identity('lane-b', team=100, kind='ranged'), identity('lane-hidden')])
    data['source'] = dict(sha256='synthetic', path='RAW_SOURCE_PATH_SENTINEL')
    for event in data['events']:
        event['source'].update(payload_hex='RAW_PACKET_SENTINEL', payload_sha256='PRIVATE_HASH_SENTINEL')
    data['summary'] = dict(future_secret='FUTURE_SUMMARY_SENTINEL')
    return data


@pytest.fixture
def context_kwargs(tmp_path):
    return dict(at=8, team=100, player='self', cache_root=make_cache(tmp_path),
        human_cards=dict(schema='conditional-human-experience/v1', cards=[]),
        mechanisms=dict(schema='champion-mechanisms/v1', sources={}, interactions=[]))


def compile_lane(bundles, kwargs, data=None):
    context = build_context(bundles, **kwargs, lane_evidence=lane_fixture() if data is None else data)
    return context, compile_frame(context)


def facts(frame, field):
    return [fact for fact in frame['facts'].values() if fact['field'] == field]


def units(lane):
    return [unit for group in lane['spatial_groups'] for unit in group['units']]+lane['unlocated_units']


def nested_keys(value):
    if isinstance(value, dict):
        return set(value).union(*(nested_keys(v) for v in value.values()))
    if isinstance(value, list):
        return set().union(*(nested_keys(v) for v in value))
    return set()


def test_lane_counts_health_and_current_position_estimates_reach_model_frame(bundles, context_kwargs):
    data = lane_fixture()
    before = deepcopy(data)
    context, compiled = compile_lane(bundles, context_kwargs, data)
    frame = compiled['frame']
    assert data == before
    assert len(frame['lane_fact_ids']) == 2
    scope = facts(frame, 'lane_observation_scope')[0]['value']
    assert scope['known_visible_alive_count'] == 2
    assert scope['previously_seen_currently_unresolved_count'] == 1
    lane_fact, = facts(frame, 'lane_current_units_and_groups')
    lane = lane_fact['value']
    assert lane['known_visible_alive_count'] == 2
    assert lane['health_known_count'] == 2 and lane['position_estimated_count'] == 2
    by_id = {unit['entity_id']: unit for unit in units(lane)}
    assert set(by_id) == {'lane-a', 'lane-b'}
    assert by_id['lane-a']['health'] == 220
    assert by_id['lane-a']['max_health'] == 400
    assert by_id['lane-a']['health_age_seconds'] == 2
    assert by_id['lane-a']['position']['relative_xz'] == [40., 0.]
    assert by_id['lane-b']['position']['relative_xz'] == [140., 0.]
    assert by_id['lane-a']['position']['path_age_seconds'] == 4
    assert 'estimate' in by_id['lane-a']['position']['semantics']
    assert 'delay' in by_id['lane-a']['health_semantics']
    assert 'observer_limited' in frame['unknowns']['waves']
    assert 'hidden' in frame['unknowns']['waves']
    assert 'minion_identity_and_waves' not in context['coverage']['unresolved']
    assert 'observer_lane_lifecycle_health_and_motion_estimates' in context['analysis_contract']['usable']


def test_model_input_has_no_raw_future_routes_or_source_hashes(bundles, context_kwargs):
    _, compiled = compile_lane(bundles, context_kwargs)
    frame = compiled['frame']
    forbidden = {'payload_hex', 'payload_sha256', 'source_sha256', 'sha256',
                 'relative_waypoints', 'path_speed', 'remaining_path_distance', 'raw_packet'}
    assert not nested_keys(frame) & forbidden
    prompt = json.dumps(model_messages(compiled, {}))
    for secret in ('RAW_SOURCE_PATH_SENTINEL', 'RAW_PACKET_SENTINEL', 'PRIVATE_HASH_SENTINEL',
                   'FUTURE_SUMMARY_SENTINEL', '12345', '7777', '8888', '9999', 'lane-hidden'):
        assert secret not in prompt
    # Evidence remains locally auditable without being serialized into messages.
    assert 'RAW_PACKET_SENTINEL' in json.dumps(compiled['audit'])


@pytest.mark.parametrize('mutation', ['future', 'hidden', 'checkpoint', 'future_identity', 'unused_summary'])
def test_future_and_hidden_lane_changes_leave_frame_and_messages_identical(bundles, context_kwargs, mutation):
    data = lane_fixture()
    _, before = compile_lane(bundles, context_kwargs, data)
    changed = deepcopy(data)
    if mutation == 'future_identity':
        changed['identities'].append(identity('FUTURE_ACTOR_SENTINEL', at=15))
    elif mutation == 'unused_summary':
        changed['summary']['future_secret'] = 'DIFFERENT_FUTURE_SENTINEL'
        changed['source']['path'] = 'CHANGED_AUDIT_PATH_SENTINEL'
    else:
        for event in changed['events']:
            selected = (mutation == 'future' and event['time_seconds'] > 8
                        or mutation == 'hidden' and event['entity_id'] == 'lane-hidden' and event['time_seconds'] > 5
                        or mutation == 'checkpoint' and event['source']['stream'] == 2)
            if not selected:
                continue
            if event['kind'] == 'health_sample':
                event['values']['health'] = 987654321
            elif event['kind'] == 'path_command':
                event['relative_waypoints'] = [[-9876, -9876], [-9000, -9000]]
    _, after = compile_lane(bundles, context_kwargs, changed)
    assert before['frame'] == after['frame']
    assert model_messages(before, {}) == model_messages(after, {})


@pytest.mark.parametrize('field,value', [('version', '16.21'), ('source', {'sha256': 'wrong-replay'}),
                                       ('schema', 'unreviewed-lanes/v1')])
def test_incompatible_lane_evidence_fails_before_model_context(bundles, context_kwargs, field, value):
    data = lane_fixture()
    data[field] = value
    with pytest.raises(ValueError):
        compile_lane(bundles, context_kwargs, data)


def test_missing_lane_evidence_preserves_existing_not_joined_contract(bundles, context_kwargs):
    context = build_context(bundles, **context_kwargs)
    compiled = compile_frame(context)
    assert 'lane_fact_ids' not in compiled['frame']
    assert compiled['frame']['unknowns']['waves'] == 'not_joined_by_this_adapter'
    assert 'minion_identity_and_waves' in context['coverage']['unresolved']


@pytest.mark.parametrize('mutation', ['wrong_time', 'wrong_team', 'future_health', 'future_position'])
def test_reused_or_future_lane_view_is_rejected_at_frame_boundary(bundles, context_kwargs, mutation):
    context, _ = compile_lane(bundles, context_kwargs)
    model = context['world']['lane_waves']['model']
    unit = units(model['lanes'][0])[0]
    if mutation == 'wrong_time':
        model['at_seconds'] = 9
    elif mutation == 'wrong_team':
        model['observer_team_id'] = 200
    elif mutation == 'future_health':
        unit['health_updated_at_seconds'] = 9
    else:
        unit['position']['path_updated_at_seconds'] = 9
    with pytest.raises(ValueError):
        compile_frame(context)


def test_nested_extra_raw_fields_do_not_enter_frame_or_messages(bundles, context_kwargs):
    context, before = compile_lane(bundles, context_kwargs)
    model = context['world']['lane_waves']['model']
    model['raw_packet'] = 'INJECTED_RAW_SENTINEL'
    lane = model['lanes'][0]
    lane['payload_hex'] = 'INJECTED_RAW_SENTINEL'
    group = lane['spatial_groups'][0]
    group['future_route'] = 'INJECTED_RAW_SENTINEL'
    unit = group['units'][0]
    unit['source_sha256'] = 'INJECTED_RAW_SENTINEL'
    unit['position']['relative_waypoints'] = [[99999, 99999]]
    model['coordinate_basis']['audit_secret'] = 'INJECTED_RAW_SENTINEL'
    model['grouping_rule']['audit_secret'] = 'INJECTED_RAW_SENTINEL'
    after = compile_frame(context)
    assert after['frame'] == before['frame']
    assert model_messages(after, {}) == model_messages(before, {})


def test_nearby_groups_are_descriptions_not_lane_priority_or_attack_claims(bundles, context_kwargs):
    _, compiled = compile_lane(bundles, context_kwargs)
    scope = facts(compiled['frame'], 'lane_observation_scope')[0]['value']
    lane = facts(compiled['frame'], 'lane_current_units_and_groups')[0]['value']
    assert scope['grouping_rule']['is_decoded_spawn_wave_id'] is False
    assert lane['complete_lane_count'] is None and lane['lane_priority'] is None
    group, = lane['spatial_groups']
    assert group['both_teams_present'] is True
    assert group['contact'] == 'opposing_units_nearby_not_proof_of_attacks'
    assert compiled['frame']['calculations'] == {}
    assert all(fact['field'] not in {'lane_priority', 'attack_target', 'push_direction'}
               for fact in compiled['frame']['facts'].values())
