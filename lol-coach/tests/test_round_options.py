"""Controlled counterfactuals. All game states and timing observations here are synthetic."""
import pytest

from lol_coach.reasoning_frame import compile_frame, digest
from lol_coach.round_options import compare_round_options
from lol_coach.round_wave_clock import birth_forecast
from test_macro_snapshot import bundles, query


@pytest.fixture
def frame(bundles):
    return compile_frame(query(bundles, player='self', at=8))['frame']


def add_fact(frame, index, *, entity, field, value, unit, scope, when=8, available=None):
    fact = dict(entity_id=entity, field=field, value=value, unit=unit, temporal_scope=scope,
                observed_at_seconds=when, age_seconds=frame['decision']['at_seconds'] - when)
    if available is not None:
        fact['available_at_seconds'] = available
    fid = 'f_' + digest(fact)[:20]
    frame['facts'][fid] = fact
    frame.setdefault(index, []).append(fid)
    frame['frame_id'] = 'frame_' + digest({k: v for k, v in frame.items() if k != 'frame_id'})[:24]
    return fid


def clock(frame, key, pair, *, entity='self', target='dragon', lane='mid', team=100,
          when=8, available=None, **kwargs):
    v = dict(clock=key, interval=pair, lane=lane, target=target, observer_team_id=team, **kwargs)
    return add_fact(frame, 'timing_fact_ids', entity=entity, field='round_timing_window',
                    value=v, unit='seconds', scope='conditional_timing_for_decision', when=when, available=available)


def compare(frame, **kwargs):
    return compare_round_options(frame, **dict(dict(lane='mid', target='dragon', help_seconds=5), **kwargs))


def test_three_departures_and_round_trip_react_to_a_single_changed_deadline(frame):
    for key, pair in [('route_duration', [3, 4]), ('target_deadline', [15, 16]),
                      ('target_work_duration', [2, 3]), ('return_duration', [3, 4]),
                      ('wave_clear_duration', [2, 7]), ('next_wave_deadline', [18, 20])]:
        clock(frame, key, pair)
    first, help_, clear = compare(frame)['options']
    assert [r['action'] for r in (first, help_, clear)] == ['leave_now', 'help_then_leave', 'clear_then_leave']
    assert (first['depart_at'], first['arrive_at'], first['return_to_lane_at']) == ([8, 8], [11, 12], [16, 19])
    assert (help_['depart_at'], help_['arrive_at'], help_['return_to_lane_at']) == ([13, 13], [16, 17], [21, 24])
    assert (clear['depart_at'], clear['arrive_at']) == ([10, 15], [13, 19])
    assert [r['target_window'] for r in (first, help_, clear)] == ['before_or_at', 'overlap', 'overlap']
    assert first['next_wave_window'] == 'overlap' and help_['next_wave_window'] == 'too_late'
    old = next(fid for fid in frame['timing_fact_ids'] if frame['facts'][fid]['value']['clock'] == 'next_wave_deadline')
    frame['timing_fact_ids'].remove(old)
    clock(frame, 'next_wave_deadline', [24, 24])
    again = compare(frame)['options'][1]
    assert again['next_wave_window'] == 'before_or_at' and help_['target_window'] == again['target_window']


def test_project_only_known_lane_minions_and_no_unsupported_arithmetic(frame):
    data = dict(lane='mid', observer_team_id=100, count_scope='own_team_observed_live_only',
                counts=[dict(team_id=100, kind='melee', count=3)], internal_secret=77)
    fid = add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
                   value=data, unit=None, scope='observer_limited_reconstructed_state')
    out = compare(frame)
    assert out['lane_observation'] == dict(fact_id=fid, lane='mid', count_scope=data['count_scope'],
        counts=data['counts'], position_samples=None,
        enemy_minions=dict(status='outside_source_coverage', observed_count=None, total_alive_count=None))
    assert [o['depart_at'] for o in out['options']] == [[8, 8], [13, 13], None]
    assert all(o['arrive_at'] is None and o['next_wave_window'] == 'unknown' for o in out['options'])
    assert all(out[k] is None for k in ('additional_objective_contribution', 'actual_arrival', 'exact_minions_forgone'))


@pytest.mark.parametrize('enemy_count', [0, 2])
def test_observer_filtered_enemy_count_is_distinct_from_the_total_alive(frame, enemy_count):
    counts = [dict(team_id=100, kind='melee', count=1)]
    if enemy_count:
        counts.append(dict(team_id=200, kind='melee', count=enemy_count))
    add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
             value=dict(lane='mid', counts=counts), unit=None, scope='observer_limited_reconstructed_state')
    lane = compare(frame)['lane_observation']
    assert lane['enemy_minions'] == dict(status='observed' if enemy_count else 'none_in_observer_sample',
                                        observed_count=enemy_count, total_alive_count=None)
    assert lane['position_samples'] is None


def test_allied_last_path_start_counts_use_each_units_timestamp(frame):
    units = [dict(entity_id=str(i), sampled_at=t, last_xz=[1, 2] if t is not None else None)
             for i, t in enumerate([6.9, 7, 8, None])]
    add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
             value=dict(lane='mid', count_scope='own_team_observed_live_only', units=units,
                        counts=[dict(team_id=100, kind='melee', count=4)]), unit=None, scope='queried_at_decision_time')
    obs = compare(frame)['lane_observation']
    assert obs['position_samples'] == dict(basis='last_observed_path_start_per_allied_minion',
        max_age_seconds=1, window_start_seconds=7, recent_count=2, older_count=1, unsampled_count=1)
    assert obs['enemy_minions']['observed_count'] is None


def test_registered_waves_keep_older_survivors_and_new_reinforcements_separate(frame):
    units = [dict(entity_id=str(i), born_at=b, kind=k, sampled_at=7, last_xz=[1, 2])
             for i, (b, k) in enumerate([(0, 'melee'), (1, 'melee'), (2, 'siege'),
                                          (4, 'melee'), (4.5, 'ranged'), (7.5, 'ranged')])]
    add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
             value=dict(lane='mid', count_scope='own_team_observed_live_only', units=units,
                        wave_spawn_clock=birth_forecast([1, 4], 8),
                        counts=[dict(team_id=100, kind=k, count=n) for k,n in [('melee', 3), ('siege', 1), ('ranged', 2)]]),
             unit=None, scope='queried_at_decision_time')
    obs = compare(frame)['lane_observation']
    parts = obs['allied_birth_cohorts']
    assert [(g['first_melee_born_at'], g['registered'], g['registered_siege'])
            for g in parts['cohorts']] == [(1, 2, 1), (4, 2, 0)]
    assert parts['unassigned_count'] == 2
    assert obs['enemy_minions']['observed_count'] is None


@pytest.mark.parametrize('unit', [
    dict(entity_id='a', sampled_at=8.1, last_xz=[1, 2]),
    dict(entity_id='a', sampled_at=8, last_xz=None)])
def test_invalid_position_sample_is_not_counted_as_recent(frame, unit):
    add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
             value=dict(lane='mid', count_scope='own_team_observed_live_only', units=[unit],
                        counts=[dict(team_id=100, kind='melee', count=1)]), unit=None, scope='queried_at_decision_time')
    with pytest.raises(ValueError, match='invalid_lane_position_sample'):
        compare(frame)


def test_current_route_is_not_reusable_after_wait_or_for_another_target(frame):
    f = clock(frame, 'immediate_route_duration', [1, 1])
    clock(frame, 'route_duration', [2, 3], entity='ally')
    clock(frame, 'route_duration', [4, 6], target='baron')
    clock(frame, 'route_duration', [4, 5], lane='top')
    clock(frame, 'route_duration', [1, 2], when=7)  # expired
    a, b, c = compare(frame)['options']
    assert (a['arrive_at'], a['evidence_ids']) == ([9, 9], [f])
    assert b['arrive_at'] is None and c['arrive_at'] is None
    assert compare(frame, help_seconds=0)['options'][1]['arrive_at'] == [9, 9]
    assert compare(frame, actor_id='ally')['options'][1]['arrive_at'] == [15, 16]


def test_marginal_objective_contribution_needs_a_matched_pair_for_this_help_duration(frame):
    clock(frame, 'target_finish_with_help', [14, 16], help_seconds=5)
    assert compare(frame)['additional_objective_contribution'] is None
    clock(frame, 'target_finish_without_help', [15, 18], help_seconds=5)
    result = compare(frame)['additional_objective_contribution']
    assert result['estimated_seconds_saved'] == [-1, 4] and len(result['evidence_ids']) == 2
    assert compare(frame, help_seconds=3)['additional_objective_contribution'] is None


def test_waiting_alone_can_rule_out_a_deadline_when_route_is_unknown(frame):
    clock(frame, 'target_deadline', [9, 12])
    clock(frame, 'next_wave_deadline', [12, 12])
    now, wait, _ = compare(frame)['options']
    assert now['target_window'] == 'unknown'
    assert wait['target_window'] == wait['next_wave_window'] == 'too_late'
    assert now['available_travel_seconds'] == [1, 4] and wait['available_travel_seconds'] == [-4, -1]
    assert wait['arrive_at'] is None


@pytest.mark.parametrize('forged', [False, True])
def test_base_birth_window_is_visible_but_never_a_tower_deadline(frame, forged):
    fc = birth_forecast([1.2, 3.2, 6.2], 8)
    if forged:
        fc['next_birth_window'] = [8, 1000]
    v = dict(lane='mid', counts=[], observer_team_id=100, wave_spawn_clock=fc)
    add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
             value=v, unit=None, scope='queried_at_decision_time')
    if forged:
        with pytest.raises(ValueError, match='invalid_wave_spawn_forecast'):
            compare(frame)
    else:
        result = compare(frame)
        assert result['lane_observation']['wave_spawn_clock']['next_birth_window'] == [8, 10]
        assert all(row['next_wave_window'] == 'unknown' for row in result['options'])


@pytest.mark.parametrize('fields', [
    dict(when=9), dict(when=7, available=9), dict(team=200), dict(pair=[2, 1]),
    dict(pair=[True, 1]), dict(pair=[-1, 2]), dict(when=7, valid_until_seconds=6)])
def test_invalid_or_out_of_scope_clocks_are_refused(frame, fields):
    clock(frame, 'route_duration', **dict({'pair': [1, 2]}, **fields))
    with pytest.raises(ValueError):
        compare(frame)


@pytest.mark.parametrize('params', [dict(actor_id='enemy'), dict(actor_id='unknown'), dict(help_seconds=-1),
                                    dict(help_seconds=True), dict(lane='nowhere'), dict(target='')])
def test_invalid_request_is_refused(frame, params):
    with pytest.raises(ValueError):
        compare(frame, **params)


def test_same_clock_twice_and_tampered_frames_are_refused(frame):
    clock(frame, 'route_duration', [3, 5])
    clock(frame, 'route_duration', [4, 5])
    with pytest.raises(ValueError, match='ambiguous'):
        compare(frame)
    frame['decision']['at_seconds'] += 2
    with pytest.raises(ValueError, match='invalid_frozen_frame'):
        compare(frame)


def test_jungle_scopes_clear_and_return_clocks_to_camp(frame):
    clock(frame, 'wave_clear_duration', [1, 2], lane='mid')
    clock(frame, 'next_wave_deadline', [12, 12], lane='mid')
    no_clock = compare(frame, lane='jungle')
    assert no_clock['lane_observation'] is None
    assert no_clock['options'][2]['depart_at'] is None
    assert no_clock['jungle_observation']['current_camp'] is None
    for key, pair in [('camp_clear_duration', [4, 6]), ('route_duration', [3, 5]),
                      ('target_work_duration', [1, 2]), ('return_to_camp_duration', [3, 4])]:
        clock(frame, key, pair, lane='jungle')
    cleared = compare(frame, lane='jungle')['options'][2]
    assert cleared['depart_at'] == [12, 14] and cleared['return_to_camp_at'] == [19, 25]
    assert cleared['return_to_lane_at'] is None and cleared['next_wave_window'] == 'unknown'


def test_jungle_nearest_camp_is_only_geometry(frame):
    frame['decision']['build'] = '16.22.836.1077'
    fid = add_fact(frame, 'allied_path_fact_ids', entity='self', field='allied_path_start_sample',
                   value={'xz': [9866, 4414], 'observer_team_id': 100},
                   scope='historical_path_start_sample', unit='map11_world_xz', when=2)
    camp = compare(frame, lane='jungle')['jungle_observation']
    assert camp['camps_by_distance_from_sample'][0]['locator'] == 'Dragon'
    assert camp['path_fact_id'] == fid and camp['age_seconds'] == 6
    assert camp['current_camp'] is None and camp['camp_presence'] == 'unknown'


@pytest.mark.parametrize('when,expected', [(7, None), (8, 12.0)])
def test_only_current_hud_can_project_constant_damage_scenario(frame,when,expected):
    frame['decision']['build'] = '16.22.836.1077'
    add_fact(frame,'personal_camp_fact_ids',entity='self',field='personal_jungle_camp_observation',
             value=dict(camp='gromp',state='engaged',observer_team_id=100,full_hp=2000,monster_hp=1500,last_full_at=4),
             unit=None,scope='historical_personal_camp_hud',when=when)
    result = compare(frame,lane='jungle')
    scenario = result['jungle_observation']['constant_damage_rate_scenario']
    assert (scenario['seconds_if_rate_held'] if scenario else None)==expected
    assert result['options'][2]['depart_at'] is None
    assert result['jungle_observation']['remaining_clear_seconds'] is None
