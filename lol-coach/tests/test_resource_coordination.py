"""Controlled decision windows; all observations in these tests are synthetic."""
import pytest

from lol_coach.round_options import resource_window
from lol_coach.round_wave_clock import birth_forecast
from test_macro_snapshot import bundles
from test_round_options import add_fact, clock, compare, frame


def on_gromp(frame):
    frame['decision']['build'] = '16.22.836.1077'
    return add_fact(frame, 'personal_camp_fact_ids', entity='self', field='personal_jungle_camp_observation',
                    value=dict(camp='gromp', state='engaged', observer_team_id=100, full_hp=2000,
                               monster_hp=1500, last_full_at=4), unit=None, scope='historical_personal_camp_hud')


@pytest.mark.parametrize('deadline, result', [(18, 'too_late'), (22, 'overlap'), (24, 'before_or_at')])
def test_jungle_route_budget_and_ally_timing(frame, deadline, result):
    camp_id = on_gromp(frame)
    for key, pair in [('target_deadline', [deadline, deadline]), ('route_duration', [1, 3])]:
        clock(frame, key, pair, lane='jungle', target='mid')
    view = resource_window(frame, compare(frame, lane='jungle', target='mid'))
    scenario = view['camp']['clear_at_constant_rate']
    assert view['timing_target'] == 'mid'
    assert view['timing_target_lane'] == 'mid' and view['timing_recipient_id'] is None
    assert scenario['depart_at_if_rate_holds'] == 20
    assert scenario['arrive_at_if_rate_holds'] == [21, 23]
    assert scenario['target_window_if_rate_holds'] == result
    assert scenario['seconds_left_for_travel_if_rate_holds'] == [deadline-20]*2
    assert scenario['evidence_id'] == camp_id
    leave, clear = view['arrival_options']
    assert leave['arrive_at'] == [9, 11]
    assert clear['depart_at'] is None
    assert view['arrival_health_resource'] is None and view['camp']['smite_ready'] is None


def test_current_only_route_does_not_transfer_to_after_clear(frame):
    on_gromp(frame)
    clock(frame, 'immediate_route_duration', [1, 1], lane='jungle')
    view = resource_window(frame, compare(frame, lane='jungle'))
    assert view['timing_target_lane'] is None and view['timing_recipient_id'] is None
    scenario = view['camp']['clear_at_constant_rate']
    assert scenario['target_window_if_rate_holds'] == 'unknown'
    assert scenario['arrive_at_if_rate_holds'] is None
    assert scenario['seconds_left_for_travel_if_rate_holds'] is None


def test_display_rounding_does_not_move_arrival_past_deadline(frame):
    frame['decision']['build'] = '16.22.836.1077'
    add_fact(frame, 'personal_camp_fact_ids', entity='self', field='personal_jungle_camp_observation',
             value=dict(camp='gromp', state='engaged', observer_team_id=100, full_hp=21,
                        monster_hp=10, last_full_at=4), unit=None, scope='historical_personal_camp_hud')
    clock(frame, 'route_duration', [1, 1], lane='jungle')
    clock(frame, 'target_deadline', [12.638, 12.638], lane='jungle')
    scenario = resource_window(frame, compare(frame, lane='jungle'))['camp']['clear_at_constant_rate']
    assert scenario['depart_at_if_rate_holds'] == 11.64
    assert scenario['target_window_if_rate_holds'] == 'before_or_at'


def test_wave_cohort_geometry_is_separate_from_arrival_or_crash(frame):
    units = [dict(entity_id=str(i), born_at=b, kind='melee', last_xz=xz, sampled_at=t)
             for i, (b, xz, t) in enumerate([(2, [0, 0], 7), (4, [6, 8], 6), (5, None, None)])]
    fid = add_fact(frame, 'lane_fact_ids', entity='lane:mid', field='lane_current_units_and_groups',
                   value=dict(lane='mid', observer_team_id=100, count_scope='own_team_observed_live_only',
                              wave_spawn_clock=birth_forecast([0, 2, 4, 6], 8), units=units,
                              counts=[dict(team_id=100, kind='melee', count=3)]),
                   unit=None, scope='queried_at_decision_time')
    view = resource_window(frame, compare(frame))
    wave, = view['lanes']
    first, next_wave = wave['registered_cohorts']
    assert first['registered'] == 1 and next_wave['registered'] == 2
    assert next_wave['position_count'] == 1 and next_wave['sample_age_seconds'] == [2, 2]
    assert next_wave['sampled_gap_from_older_cohort_world_units'] == 10
    assert wave['enemy_coverage'] == 'outside_source_coverage'
    assert wave['crash_at'] is None and wave['next_clash_at'] is None
    assert wave['fact_id'] == fid
    assert set(view['wave_actions_to_compare']) == {'leave_untouched', 'last_hit', 'slow_push', 'fast_push'}
    assert view['timing_target'] == 'dragon' and view['timing_target_lane'] is None


def test_others_can_finish_without_declaring_that_they_agreed(frame):
    clock(frame, 'target_finish_with_help', [14, 15], help_seconds=5)
    clock(frame, 'target_finish_without_help', [16, 17], help_seconds=5)
    view = resource_window(frame, compare(frame))
    assert view['target_work_comparison']['conditional_effect']['estimated_seconds_saved'] == [1, 3]
    assert view['timing_recipient_id'] is None and view['target_arrival_deadline'] is None


def test_resource_window_rejects_other_frame_or_actor(frame):
    c = compare(frame)
    for key in ('frame_id', 'actor_id', 'observer_team_id'):
        with pytest.raises(ValueError, match='scope_mismatch'):
            resource_window(frame, dict(c, **{key:'other'}))
