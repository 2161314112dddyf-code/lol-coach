"""Synthetic combat-to-model visibility/time contracts; not gameplay validation."""
from copy import deepcopy
import json

import pytest

from lol_coach import lane_wave as wave
from test_lane_wave import SHA, VERSION, bundle, event, hp, identity, path, units, vis


def component(at=9, value=25., actor='a', stream=1, **extra):
    return event(at, 'reported_health_loss_component', actor=actor, stream=stream,
        reported_entity_id=actor, value=value, unit='health_points', **extra)


def combat(events=None, rejected=()):
    return dict(schema='lane-combat-evidence/v1', version=VERSION,
        source={'sha256': SHA, 'fixture': 'synthetic'}, recording_end_seconds=100,
        events=[component()] if events is None else events, rejected=list(rejected))


def build(data=None, evidence=None, at=10):
    return wave.build_lane_view(bundle() if data is None else data,
        at=at, team=100, source_sha256=SHA, combat=evidence)


def admitted(data=None, evidence=None, at=10):
    return wave.model_view(build(data, evidence, at), at=at, team=100)


def damage(data=None, evidence=None, at=10):
    return admitted(data, evidence, at)['recent_health_loss']


def located(row, offset):
    row['source']['decompressed_offset'] = offset
    return row


@pytest.mark.parametrize('field,value', [('schema', 'other'), ('version', '16.21'),
                                       ('source', {'sha256': 'b'*64})])
def test_combat_schema_version_and_source_mismatch_are_rejected(field, value):
    supplied = combat()
    supplied[field] = value
    with pytest.raises(ValueError, match='combat source/build/schema'):
        admitted(evidence=supplied)


def test_missing_combat_is_unavailable_not_zero_measured_damage():
    result = damage()
    assert result['status'] == 'unavailable'
    assert result['components'] == []
    assert result['unparsed_visible_records'] is None
    assert result['attack_count'] is None
    assert result['attacker_attribution'] is None


@pytest.mark.parametrize('identities', [[identity(team=100)], [identity(team=200)]])
def test_no_explicit_enter_means_unknown_for_allies_and_enemies(identities):
    data = bundle([hp(), path()], identities)
    result = damage(data, combat())
    assert result['components'] == []
    assert result['unparsed_visible_records'] == 0


@pytest.mark.parametrize('state', [False, None])
def test_hidden_or_unknown_interval_components_do_not_enter_model(state):
    data = bundle([vis(), hp(), path(), vis(8, visible=state)])
    supplied = combat([component(9, 999)])
    result = damage(data, supplied)
    assert result['components'] == []
    changed = deepcopy(supplied)
    changed['events'][0]['value'] = 123456
    changed['events'][0]['opaque_middle_hex'] = 'HIDDEN_SCALAR_SECRET'
    assert admitted(data, supplied) == admitted(data, changed)


def test_future_checkpoint_and_never_known_entity_components_are_not_consumed():
    supplied = combat([component(11, 111), component(9, 222, stream=2),
                       component(9, 333, actor='never_known')])
    data = bundle(identities=[identity(), identity('future_identity', at=80)])
    supplied['events'].append(component(9, 444, actor='future_identity'))
    result = admitted(data, supplied)
    assert result['recent_health_loss']['components'] == []
    changed = deepcopy(supplied)
    for row in changed['events']:
        row['value'] = 999999
        row['amount_wire_hex'] = 'FUTURE_OR_CHECKPOINT'
    assert admitted(data, changed) == result


def test_other_observer_enter_cannot_authorize_health_loss_component():
    data = bundle([vis(team=200), hp(), path()])
    assert damage(data, combat())['components'] == []


def test_equal_timestamp_enter_uses_packet_order_before_or_after_damage():
    data = bundle([located(vis(8), 200), hp(8.5), path(8.6)])
    supplied = combat([located(component(8, 10), 199), located(component(8, 20), 201)])
    result = damage(data, supplied)
    assert [row['value'] for row in result['components']] == [20]
    supplied['events'].reverse()
    assert damage(data, supplied) == result


def test_equal_timestamp_leave_uses_packet_order_before_or_after_damage():
    data = bundle([vis(), hp(), path(), located(vis(8, visible=False), 200)])
    supplied = combat([located(component(8, 10), 199), located(component(8, 20), 201)])
    assert [row['value'] for row in damage(data, supplied)['components']] == [10]


def test_before_identity_enter_and_damage_cannot_be_retroactively_authorized():
    data = bundle([located(vis(8), 100), hp(8.5)],
                  [located(identity(at=8), 200)])
    supplied = combat([located(component(8, 1), 150), located(component(8, 2), 250)])
    assert damage(data, supplied)['components'] == []


def test_reentry_does_not_backfill_hidden_damage_and_retains_only_seen_history():
    data = bundle([vis(), hp(), path(), vis(8, visible=False), vis(9)])
    supplied = combat([component(7.5, 10), component(8.5, 999), component(9.5, 20)])
    result = damage(data, supplied)
    assert [(row['at_seconds'], row['value']) for row in result['components']] == [(7.5, 10), (9.5, 20)]
    at_enter = damage(data, supplied, at=9)
    assert [row['value'] for row in at_enter['components']] == [10]


def test_three_second_window_includes_both_boundaries_and_excludes_neighbors():
    supplied = combat([component(6.999, 1), component(7, 2), component(9, 3),
                       component(10, 4), component(10.001, 5)])
    result = damage(evidence=supplied)
    assert result['window_seconds'] == 3
    assert [(e['at_seconds'], e['value']) for e in result['components']] == [(7, 2), (9, 3), (10, 4)]


def test_rejected_count_uses_visible_window_not_whole_replay_or_checkpoint():
    data = bundle([vis(), hp(), path(), vis(8, visible=False), vis(9)])
    rejected = [component(6, 1), component(7, 2), component(8.5, 3), component(9.5, 4),
                component(11, 5), component(9.7, 6, stream=2), component(9.7, 7, actor='unknown')]
    for row in rejected:
        row['reason'] = 'unknown scalar layout'
        row['payload_hex'] = 'REJECTED_RAW_SECRET'
    supplied = combat([], rejected)
    result = build(data, supplied)
    model = wave.model_view(result, at=10, team=100)
    assert model['recent_health_loss']['components'] == []
    assert model['recent_health_loss']['unparsed_visible_records'] == 2
    assert len(result['audit']['health_loss_components']) == 2
    assert 'REJECTED_RAW_SECRET' not in json.dumps(model)
    changed = deepcopy(supplied)
    changed['rejected'].append(component(90, 1000))
    changed['rejected'][2]['reason'] = 'HIDDEN_REASON'
    assert admitted(data, changed) == model


def test_component_can_exceed_hp_without_becoming_attack_or_attacker_claim():
    supplied = combat([component(9, 1000, attack_count=7, attacker_entity_id='unknown_attacker')])
    model = admitted(evidence=supplied)
    assert units(model)[0]['health'] == 100
    result = model['recent_health_loss']
    assert result['components'][0]['value'] == 1000
    assert result['attack_count'] is None and result['attacker_attribution'] is None
    assert 'attack_count' not in result['components'][0]
    assert 'attacker_entity_id' not in result['components'][0]
    assert 'overkill_possible' in result['semantics']
    assert model['known_visible_alive_count'] == 1


def test_reported_recipient_mismatch_rejects_visible_component():
    supplied = combat()
    supplied['events'][0]['reported_entity_id'] = 'different_actor'
    with pytest.raises(ValueError, match='Invalid named lane health-loss'):
        admitted(evidence=supplied)


@pytest.mark.parametrize('value', [-1, float('nan'), float('inf'), True, '100'])
def test_invalid_visible_component_values_are_rejected(value):
    with pytest.raises(ValueError, match='Invalid named lane health-loss'):
        admitted(evidence=combat([component(value=value)]))


def test_future_combat_and_zero_timestamps_are_rejected_at_model_admission():
    data = bundle([vis(), hp(), path(), hp(9, health=0)])
    original = build(data, combat())
    for namespace in ('recent_health_loss', 'recent_zero_health_events'):
        dirty = deepcopy(original)
        rows = dirty['model'][namespace]['components'] if namespace == 'recent_health_loss' else dirty['model'][namespace]
        assert rows
        rows[0]['at_seconds'] = 10.001
        with pytest.raises(ValueError, match='Future or out-of-window lane combat'):
            wave.model_view(dirty, at=10, team=100)


def test_out_of_window_combat_timestamp_rejected_at_model_admission():
    dirty = build(evidence=combat())
    dirty['model']['recent_health_loss']['components'][0]['at_seconds'] = 6.999
    with pytest.raises(ValueError, match='Future or out-of-window lane combat'):
        wave.model_view(dirty, at=10, team=100)


def test_recent_zero_health_requires_seen_sample_and_three_second_window():
    identities = [identity('a'), identity('b'), identity('c'), identity('d')]
    data = bundle([vis(actor='a'), hp(9, actor='a', health=0),
                   vis(actor='b'), hp(6, actor='b', health=0),
                   vis(actor='c'), vis(8, actor='c', visible=False), hp(9, actor='c', health=0),
                   hp(9, actor='d', health=0)], identities)
    result = admitted(data, combat([]))
    assert result['recent_zero_health_events'] == [dict(entity_id='a', team_id=100, kind='melee', at_seconds=9)]


def test_raw_payload_audit_and_extra_attribution_fields_never_reach_model():
    supplied = combat([component(9, 25, payload_hex='WIRE_SECRET',
        amount_wire_hex='WIRE_SECRET', source_reference={'raw': 'WIRE_SECRET'},
        attacker_entity_id='WIRE_SECRET')])
    original = build(evidence=supplied)
    expected = wave.model_view(original, at=10, team=100)
    dirty = deepcopy(original)
    dirty['audit'] = {'raw': 'AUDIT_SECRET'}
    dirty['extra_raw'] = 'AUDIT_SECRET'
    dirty['model']['recent_health_loss']['payload_hex'] = 'WIRE_SECRET'
    row = dirty['model']['recent_health_loss']['components'][0]
    row.update(payload_hex='WIRE_SECRET', raw_source={'hash': 'AUDIT_SECRET'},
               attacker_entity_id='ATTACKER_SECRET', attack_count=999)
    clean = wave.model_view(dirty, at=10, team=100)
    assert clean == expected
    assert all(secret not in json.dumps(clean) for secret in ('WIRE_SECRET', 'AUDIT_SECRET', 'ATTACKER_SECRET'))


@pytest.mark.parametrize('points,motion,velocity', [([[0, 0], [1000, 0]], 'moving_estimate', [100., 0.]),
    ([[10, 20]], 'single_point_hold', [0., 0.]),
    ([[0, 0], [10, 0]], 'planned_endpoint_estimate', [0., 0.])])
def test_velocity_is_prior_point_one_second_fraction_estimate_not_enemy_route(points, motion, velocity):
    data = bundle([vis(), hp(), path(points=points)], [identity(team=200)])
    model = admitted(data, combat([]))
    position = units(model)[0]['position']
    assert position['motion'] == motion
    assert position['velocity_xz_estimate'] == velocity
    assert position['velocity_interval_seconds'] == .1
    assert 'relative_waypoints' not in json.dumps(model)
    assert 'path_speed' not in json.dumps(model)
    assert 'not_direct_position_or_proven_arrival' in position['semantics']


def test_new_path_has_no_backward_velocity_and_future_path_cannot_rewrite_it():
    data = bundle([vis(), hp(), path(10, points=[[3, 4], [1000, 4]]),
                   path(11, points=[[9999, 9999]])], [identity(team=200)])
    model = admitted(data, combat([]))
    position = units(model)[0]['position']
    assert position['relative_xz'] == [3, 4]
    assert position['velocity_xz_estimate'] is None
    assert position['velocity_interval_seconds'] == 0
    changed = deepcopy(data)
    changed['events'][-1]['relative_waypoints'] = [[-9000, -9000]]
    assert admitted(changed, combat([])) == model


def test_combat_admission_does_not_mutate_inputs():
    data = bundle()
    supplied = combat()
    saved = deepcopy((data, supplied))
    result = admitted(data, supplied)
    result['recent_health_loss']['components'][0]['value'] = 999
    assert (data, supplied) == saved
