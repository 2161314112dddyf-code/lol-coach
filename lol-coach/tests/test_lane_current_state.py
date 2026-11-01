"""Synthetic current-state contracts, separate from real checkpoint evidence."""
from copy import deepcopy

import pytest

from lol_coach.lane_current_state import reconstruct_lane_current_state


def row(at, kind, actor='a', stream=1, **extra):
    return dict(entity_id=actor, time_seconds=at, kind=kind,
                source=dict(stream=stream, chunk=1, decompressed_offset=int(at*100)), **extra)


def identity(actor='a', team=200, kind='melee', at=1, **extra):
    return row(at, 'identity', actor, identity=dict(team_id=team, lane='middle', kind=kind, **extra))


def hp(at, value=None, maximum=None, **extra):
    values = {}
    if value is not None:
        values['health'] = value
    if maximum is not None:
        values['max_health'] = maximum
    return row(at, 'health_sample', values=values, fields={}, **extra)


def vis(at, state=True, team=100, **extra):
    kind = 'visibility_unknown_barrier' if state is None else 'visibility_enter' if state else 'visibility_leave'
    return row(at, kind, observer_team_id=team, visible=state, **extra)


def bundle(events=(), identities=None):
    return dict(schema='lane-dynamics-evidence/v1', version='16.20.824.8524',
                recording_end_seconds=100, source={'fixture': 'synthetic'},
                identities=[identity()] if identities is None else identities, events=list(events))


def query(data, at=50, team=100):
    return reconstruct_lane_current_state(data, at, team)


def state(data, at=50, team=100):
    return query(data, at, team)['entities'][0]['current_state']


def test_sparse_health_persists_for_visible_interval_with_age_and_source():
    data = bundle([vis(2), hp(3, 100, 400), hp(4, 90)])
    result = query(data)
    current = result['entities'][0]['current_state']
    assert current['alive'] is True
    assert current['health']['health']['value'] == 90
    assert current['health']['health']['age_seconds'] == 46
    assert current['health']['max_health']['value'] == 400
    assert current['health']['max_health']['age_seconds'] == 47
    assert current['health']['health']['source']['decompressed_offset'] == 400
    assert current['replication_delay_unknown'] is True
    assert current['health']['health']['exact_simulation_value'] is False
    assert current['health']['health']['freshness'] == 'retained_within_visible_interval'
    assert current['continuous_visible_interval_start_seconds'] == 2
    assert result['known_visible_alive_counts'] == [dict(team_id=200, lane='middle', kind='melee', count=1, entity_ids=['a'])]
    assert result['replay_active_count'] is None


def test_zero_then_movement_and_reentry_never_revive():
    data = bundle([vis(2), hp(3, 0), row(4, 'path_command', relative_waypoints=[[1, 2]]),
                   row(5, 'uninterpreted_167'), vis(6, False), vis(7)])
    current = state(data)
    assert current['alive'] is False
    assert current['lifecycle_status'] == 'observed_zero_health'
    assert current['lifecycle_evidence']['observed_at_seconds'] == 3
    assert current['exact_simulation_death_time'] is None
    assert current['health']['health'] is None
    assert query(data)['known_visible_alive_counts'] == []


def test_zero_current_health_is_available_before_visibility_loss():
    current = state(bundle([vis(2), hp(3, 100), hp(4, 0)]))
    assert current['alive'] is False
    assert current['health']['health']['value'] == 0


@pytest.mark.parametrize('barrier', [False, None])
def test_hidden_health_and_death_cannot_refresh_current_or_history(barrier):
    data = bundle([vis(2), hp(3, 100, 400), vis(4, barrier), hp(5, 0),
                   row(6, 'terminal_removal_candidate', payload_hex='aa')])
    result = query(data)
    entity = result['entities'][0]
    assert entity['current_state']['alive'] is None
    assert entity['current_state']['health'] == {'health': None, 'max_health': None}
    assert entity['last_health_samples']['health']['value'] == 100
    assert entity['zero_health_sample'] is None
    assert not entity['current_state']['decision_input_eligible']
    altered = deepcopy(data)
    altered['events'][3]['values'] = {'health': 999999}
    altered['events'][4]['payload_hex'] = 'secret'
    assert query(altered) == result


def test_reentry_starts_empty_then_sparse_new_fields_fill_independently():
    data = bundle([vis(2), hp(3, 100, 400), vis(4, False), hp(5, 90, 500),
                   vis(6), hp(7, 80)])
    assert state(data, 6)['health'] == {'health': None, 'max_health': None}
    current = state(data, 8)
    assert current['alive'] is True
    assert current['health']['health']['value'] == 80
    assert current['health']['max_health'] is None
    assert current['continuous_visible_interval_start_seconds'] == 6


def test_known_terminal_fact_survives_visibility_loss():
    current = state(bundle([vis(2), hp(3, 0), vis(4, False)]))
    assert current['alive'] is False
    assert current['decision_input_eligible'] is True
    assert current['health']['health'] is None


def test_stream_two_identity_health_and_490_never_enter_live_state():
    data = bundle([vis(2), hp(3, 100), hp(4, 0, stream=2),
                   row(5, 'terminal_removal_candidate', stream=2)])
    assert state(data)['alive'] is True
    assert state(data)['health']['health']['value'] == 100
    assert query(data, team=None)['replay_active_count'] == 1


def test_research_mode_counts_active_but_is_not_model_input():
    data = bundle([hp(2, 100), row(3, 'terminal_removal_candidate')],
                  identities=[identity(), identity('b')])
    result = query(data, team=None)
    assert result['replay_active_count'] == 1
    assert result['known_visible_alive_counts'] == []
    assert result['mode'] == 'research_omniscient'
    assert result['decision_input_eligible'] is False
    assert result['entities'][0]['current_state']['alive'] is False
    assert result['entities'][0]['current_state']['health']['health'] is None
    assert all(not e['current_state']['decision_input_eligible'] for e in result['entities'])


def test_future_and_checkpoint_mutation_do_not_affect_current_state():
    data = bundle([vis(2), hp(3, 100), hp(80, 0), hp(4, 0, stream=2)])
    changed = deepcopy(data)
    changed['events'][2]['values']['health'] = 123456
    changed['events'][3]['values']['health'] = 123456
    changed['identities'].append(identity('future', at=80))
    assert query(data) == query(changed)


def test_teams_need_enter_even_for_allies_and_other_channels_do_not_grant_visibility():
    data = bundle([hp(2, 100), vis(3, team=200)], identities=[identity(team=100)])
    assert query(data)['entities'] == []
    assert query(data)['known_visible_alive_counts'] == []


def test_super_classification_is_time_and_observer_bounded():
    data = bundle([vis(2)], identities=[identity(kind='super', classification_available_at=80)])
    assert query(data)['entities'][0]['identity']['kind'] == 'super_candidate'
    assert query(data, team=None)['entities'][0]['identity']['kind'] == 'super_candidate'
    assert query(data, 90)['entities'][0]['identity']['kind'] == 'super_candidate'
    assert query(data, 90, None)['entities'][0]['identity']['kind'] == 'super'


def test_counts_group_only_visible_alive_entities_by_identity():
    data = bundle([vis(2), vis(2, actor='b'), vis(2, actor='c'), vis(2, actor='d'),
                   hp(3, 0, actor='c'), vis(4, False, actor='d')],
                  identities=[identity(), identity('b', team=100, kind='ranged'),
                              identity('c'), identity('d'), identity('unseen')])
    counts = query(data)['known_visible_alive_counts']
    assert sum(r['count'] for r in counts) == 2
    assert {tuple(r['entity_ids']) for r in counts} == {('a',), ('b',)}
    assert query(data)['counts_scope'] == 'explicitly_visible_named_lane_units_only'


def test_missing_health_is_none_without_inventing_zero_or_using_max_health():
    current = state(bundle([vis(2), hp(3, maximum=400)]))
    assert current['alive'] is True
    assert current['health']['health'] is None
    assert current['health']['max_health']['value'] == 400


def test_contradictory_positive_after_zero_is_not_current_or_revival():
    current = state(bundle([vis(2), hp(3, 0), hp(4, 100)]))
    assert current['alive'] is False
    assert current['health']['health'] is None
    assert current['conflicts'] == ['positive_health_with_terminal_lifecycle']


def test_input_is_not_mutated_and_unknown_position_pressure_remain_unknown():
    data = bundle([vis(2), hp(3, 100)])
    original = deepcopy(data)
    result = query(data)
    result['entities'][0]['current_state']['health']['health']['value'] = 7
    assert data == original
    assert result['current_position'] is None
    assert result['lane_priority'] is None


@pytest.mark.parametrize('at', [-1, 101, float('nan')])
def test_time_validation_is_retained(at):
    with pytest.raises(ValueError):
        query(bundle(), at)


def test_build_gate_is_retained():
    data = bundle()
    data['version'] = '16.21.8299102'
    with pytest.raises(ValueError):
        query(data)
