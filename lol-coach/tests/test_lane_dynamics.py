"""Synthetic temporal/privacy contracts; these do not validate game semantics."""
from copy import deepcopy
import json

import pytest

from lol_coach.lane_dynamics import query_at, VERSION


ACTOR = '0x40000001'


def source(offset, stream=1, **extra):
    return dict(stream=stream, chunk=2, decompressed_offset=offset, **extra)


def identity(at=1, *, actor=ACTOR, team=200, kind='melee', stream=1, offset=10, **extra):
    return dict(entity_id=actor, time_seconds=at, source=source(offset, stream),
                identity=dict(team_id=team, lane='middle', kind=kind, **extra))


def event(at, kind, *, actor=ACTOR, stream=1, offset=None, **extra):
    return dict(entity_id=actor, time_seconds=at,
                source=source(int(at*100) if offset is None else offset, stream),
                kind=kind, **extra)


def hp(at, health=None, maximum=None, **kwargs):
    values = {}
    if health is not None:
        values['health'] = health
    if maximum is not None:
        values['max_health'] = maximum
    return event(at, 'health_sample', values=values, fields={}, **kwargs)


def visibility(at, visible, team=100, **kwargs):
    kind = 'visibility_enter' if visible else 'visibility_leave'
    if visible is None:
        kind = 'visibility_unknown_barrier'
    return event(at, kind, observer_team_id=team, visible=visible, **kwargs)


def bundle(events=(), identities=None):
    return dict(schema='lane-dynamics-evidence/v1', version=VERSION,
        source={'fixture': 'synthetic'}, recording_end_seconds=100,
        identities=[identity()] if identities is None else identities, events=list(events))


def entity(data, at, team=None):
    return query_at(data, at, team)['entities'][0]


def test_future_record_changes_do_not_change_prefix_including_future_identity_witness():
    data = bundle([visibility(2, True), hp(3, 123), hp(10, 10)], identities=[
        identity(retrospective_witness={'time_seconds': 80, 'value': 900}), identity(80, actor='future')])
    changed = deepcopy(data)
    changed['events'][2]['values'] = {'health': 99999, 'future_secret': 1}
    changed['events'].append(event(90, 'terminal_removal_candidate', payload_hex='secret'))
    changed['identities'][0]['identity']['retrospective_witness'] = {'totally': 'different'}
    changed['identities'][1]['identity']['kind'] = 'ranged'
    for team in (None, 100):
        assert query_at(data, 5, team) == query_at(changed, 5, team)


def test_team_never_lists_unseen_enemy_or_implicitly_visible_allied_identities():
    data = bundle([hp(2, 10)], identities=[identity(), identity(actor='ally', team=100)])
    assert query_at(data, 3, 100)['entities'] == []
    assert len(query_at(data, 3)['entities']) == 2


def test_identity_observer_availability_starts_at_first_enter_never_spawn_or_reentry():
    data = bundle([visibility(3, True), visibility(4, False), visibility(5, True)])
    assert query_at(data, 2, 100)['entities'] == []
    first = entity(data, 3, 100)
    assert first['identity_available_to_observer_at_seconds'] == 3
    assert first['identity_evidence']['source_recorded_at_seconds'] == 1
    assert 'observed_at_seconds' not in first['identity_evidence']
    assert entity(data, 6, 100)['identity_available_to_observer_at_seconds'] == 3
    assert entity(data, 2)['identity_available_to_observer_at_seconds'] == 1


def test_initial_unknown_and_hidden_health_removal_and_opaque_packets_are_isolated():
    events = [hp(1.5, 999), visibility(2, True), hp(3, 100), visibility(4, False),
              hp(5, 0), event(6, 'terminal_removal_candidate', payload_hex='hidden-removal'),
              event(7, 'uninterpreted_167', payload_hex='hidden-opaque')]
    data = bundle(events)
    limited = entity(data, 8, 100)
    assert limited['last_health_samples']['health']['value'] == 100
    assert limited['current_observed'] is None
    assert limited['zero_health_sample'] is None
    assert limited['removal_candidate'] is None
    assert limited['lifecycle_evidence'] == []
    altered = deepcopy(data)
    altered['events'][0]['values']['health'] = 123456
    altered['events'][4]['values']['health'] = 987654
    altered['events'][5]['payload_hex'] = 'replacement'
    altered['events'][6]['payload_hex'] = 'replacement'
    assert query_at(altered, 8, 100) == query_at(data, 8, 100)
    assert entity(data, 8)['zero_health_sample']['value'] == 0


def test_checkpoint_cannot_backfill_identity_visibility_health_or_removal():
    data = bundle([visibility(2, True), hp(3, 100), hp(4, 0, stream=2),
        visibility(5, False, stream=2), event(6, 'terminal_removal_candidate', stream=2),
        hp(0.5, 500, actor='checkpoint', stream=1)], identities=[identity(),
        identity(0, actor='checkpoint', stream=2)])
    result = query_at(data, 10, 100)
    assert len(result['entities']) == 1
    current = result['entities'][0]
    assert current['last_health_samples']['health']['value'] == 100
    assert current['visibility']['visible'] is True
    assert current['zero_health_sample'] is None
    assert current['removal_candidate'] is None


def test_unknown_fields_stay_absent_not_zero_or_copied_from_other_field():
    result = entity(bundle([hp(2, maximum=400)]), 3)
    assert set(result['last_health_samples']) == {'max_health'}
    assert result['zero_health_sample'] is None
    assert result['last_path_command'] is None
    assert result['last_static_format_position_sample'] is None
    assert result['alive'] is None


def test_reentry_clears_current_interval_without_reusing_hidden_or_old_samples():
    data = bundle([visibility(2, True), hp(3, 100, 400), visibility(4, False),
                   hp(5, 200, 500), visibility(6, True), hp(7, 250)])
    reentered = entity(data, 6, 100)
    assert reentered['last_health_samples']['health']['value'] == 100
    assert reentered['current_observed']['health_samples'] == {}
    fresh = entity(data, 8, 100)
    assert fresh['current_observed']['health_samples']['health']['value'] == 250
    assert 'max_health' not in fresh['current_observed']['health_samples']
    assert fresh['last_health_samples']['max_health']['value'] == 400
    assert fresh['last_health_samples']['health']['age_seconds'] == 1


def test_unknown_barrier_discards_current_interval_and_needs_new_enter():
    data = bundle([visibility(2, True), hp(3, 100), visibility(4, None, team=None), hp(5, 0)])
    result = entity(data, 6, 100)
    assert result['visibility']['visible'] is None
    assert result['current_observed'] is None
    assert result['last_health_samples']['health']['value'] == 100
    assert result['zero_health_sample'] is None


def test_other_observer_channel_cannot_open_or_close_requested_channel():
    data = bundle([visibility(2, True, team=200), hp(3, 100), visibility(4, True),
                   visibility(5, False, team=200), hp(6, 200)])
    assert query_at(data, 3, 100)['entities'] == []
    assert entity(data, 7, 100)['last_health_samples']['health']['value'] == 200
    assert entity(data, 7, 200)['last_health_samples']['health']['value'] == 100


def test_uninterpreted_167_never_infers_death_removal_or_visibility():
    data = bundle([visibility(2, True), hp(3, 100), event(4, 'uninterpreted_167', payload_hex='00')])
    result = entity(data, 5, 100)
    assert result['alive'] is None
    assert result['zero_health_sample'] is None
    assert result['removal_candidate'] is None
    assert result['visibility']['visible'] is True
    assert result['lifecycle_evidence'][0]['kind'] == 'uninterpreted_167'
    assert result['last_health_samples']['health']['value'] == 100


def test_zero_and_removal_are_distinct_historical_evidence_not_survivor_count():
    data = bundle([hp(2, 0), event(3, 'terminal_removal_candidate', payload_hex='00')])
    result = query_at(data, 5)
    current = result['entities'][0]
    assert current['zero_health_sample']['observed_at_seconds'] == 2
    assert current['removal_candidate']['observed_at_seconds'] == 3
    assert current['removal_candidate']['exact_death_time'] is None
    assert [e['kind'] for e in current['lifecycle_evidence']] == ['zero_health_sample', 'terminal_removal_candidate']
    assert result['current_position'] is None
    assert result['alive_count'] is None
    assert result['lane_priority'] is None
    assert result['decision_input_eligible'] is False


def test_source_packet_and_subrecord_order_is_stable_at_same_timestamp():
    earlier = hp(2, 100, offset=30)
    later = hp(2, 200, offset=30)
    earlier['source'].update(decoded_record_offset=5, decoded_group_offset=10)
    later['source'].update(decoded_record_offset=5, decoded_group_offset=20)
    data = bundle([later, earlier, visibility(2, True, offset=20)])
    assert entity(data, 2, 100)['last_health_samples']['health']['value'] == 200
    reversed_data = deepcopy(data)
    reversed_data['events'].reverse()
    assert query_at(data, 2, 100) == query_at(reversed_data, 2, 100)


def test_events_before_live_identity_are_ignored_even_with_equal_timestamp():
    data = bundle([visibility(1, True, offset=1), hp(1, 500, offset=2),
                   hp(1, 100, offset=11)], identities=[identity(offset=10)])
    assert query_at(data, 2, 100)['entities'] == []
    assert entity(data, 2)['last_health_samples']['health']['value'] == 100


def test_future_super_label_time_basis_and_witness_do_not_leak():
    data = bundle([visibility(2, True)], identities=[identity(kind='super',
        classification_available_at=20, classification_basis='future-secret',
        witness={'secret': 999})])
    assert entity(data, 5)['identity']['kind'] == 'super_candidate'
    assert 'future-secret' not in json.dumps(query_at(data, 5))
    assert 'classification_available_at' not in entity(data, 5)['identity']
    changed = deepcopy(data)
    changed['identities'][0]['identity']['classification_available_at'] = 80
    changed['identities'][0]['identity']['classification_basis'] = 'another-future'
    for team in (None, 100):
        assert query_at(changed, 5, team) == query_at(data, 5, team)
    assert entity(data, 25)['identity']['kind'] == 'super'
    # The retrospective witness carries no observer permission, even after t.
    assert entity(data, 25, 100)['identity']['kind'] == 'super_candidate'


def test_enemy_path_discloses_only_historical_start_not_plan_or_speed():
    data = bundle([visibility(2, True), event(3, 'path_command',
        relative_waypoints=[[10, 20], [100, 200]], path_speed=325)])
    enemy = entity(data, 4, 100)['last_path_command']
    assert enemy['first_relative_point_candidate'] == [10, 20]
    assert 'relative_waypoints' not in enemy
    assert 'path_speed' not in enemy
    assert enemy['age_seconds'] == 1
    assert enemy['actual_arrival'] is None
    assert entity(data, 4)['last_path_command']['relative_waypoints'] == [[10, 20], [100, 200]]
    changed = deepcopy(data)
    changed['events'][1]['relative_waypoints'][1] = [999, 999]
    changed['events'][1]['path_speed'] = 999
    assert query_at(changed, 4, 100) == query_at(data, 4, 100)


def test_allied_path_still_requires_enter_but_is_available_as_recorded_plan():
    data = bundle([visibility(2, True), event(3, 'path_command',
        relative_waypoints=[[10, 20], [100, 200]], path_speed=325)], identities=[identity(team=100)])
    assert entity(data, 4, 100)['last_path_command']['path_speed'] == 325
    assert entity(data, 4, 100)['current_position'] is None


def test_static_format_sample_is_historical_and_not_promoted_to_current_position():
    data = bundle([event(3, 'static_format_position_sample', position_xz=[123, 456],
                         decoded_position_offset=90)])
    result = entity(data, 20)
    assert result['last_static_format_position_sample']['position_xz'] == [123, 456]
    assert result['last_static_format_position_sample']['age_seconds'] == 17
    assert result['current_position'] is None
    assert result['last_static_format_position_sample']['source']['decoded_position_offset'] == 90


def test_query_does_not_mutate_bundle_or_share_mutable_output_objects_with_it():
    data = bundle([visibility(2, True), hp(3, 100)])
    original = deepcopy(data)
    result = query_at(data, 5, 100)
    assert data == original
    result['entities'][0]['identity']['team_id'] = 123
    result['entities'][0]['last_health_samples']['health']['source']['chunk'] = 99
    result['audit']['source']['fixture'] = 'changed'
    assert data == original


@pytest.mark.parametrize('at', [-1, 101, float('nan'), float('inf'), float('-inf'), True, '5', None])
def test_invalid_cutoff_rejected(at):
    with pytest.raises(ValueError, match='cutoff'):
        query_at(bundle(), at)


@pytest.mark.parametrize('team', [0, 300, 100.0, True, '100'])
def test_invalid_observer_rejected(team):
    with pytest.raises(ValueError, match='observer'):
        query_at(bundle(), 5, team)


@pytest.mark.parametrize('end', [-1, float('nan'), float('inf'), True, None])
def test_invalid_recording_end_rejected(end):
    data = bundle()
    data['recording_end_seconds'] = end
    with pytest.raises(ValueError, match='recording end'):
        query_at(data, 0)


def test_version_schema_gates_and_zero_end_inclusive_cutoff():
    data = bundle(identities=[])
    data['recording_end_seconds'] = 0
    assert query_at(data, 0)['entities'] == []
    data['version'] = '16.21'
    with pytest.raises(ValueError, match='build'):
        query_at(data, 0)
    data['version'] = VERSION
    data['schema'] = 'other'
    with pytest.raises(ValueError, match='schema'):
        query_at(data, 0)
