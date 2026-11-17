"""Synthetic controls for one support's frozen lane read through the regular round tool."""
from copy import deepcopy

import pytest

from lol_coach.round_plan import review_round_plan
from test_round_chain import bundle_at, freeze
from test_round_options import add_fact, clock


ROLES = {'support': 'self', 'carry': 'ally', 'enemy_support': 'tahm', 'enemy_carry': 'enemy'}


def lane_case(build='16.22.836.1077', carry='Caitlyn'):
    b = bundle_at(10)
    f = b['frame']
    f['decision']['build'] = build
    f['lineup'][0]['champion'] = 'Pantheon'
    f['lineup'][1]['champion'] = carry
    f['lineup'][2]['champion'] = 'KogMaw'
    for actor, champ in [('tahm', 'TahmKench'), ('jungler', 'MasterYi')]:
        f['lineup'].append(dict(entity_id=actor, champion=champ, relation='enemy',
                                current_fact_ids=[], history_fact_ids=[]))
    f['task'].update(bottom_lane_actors=dict(ROLES), bottom_lane_review='support-lane/v1',
                     round_comparison=dict(lane='bot', target='river_entrance', help_seconds=3))
    return freeze(b)


def seen(frame, actor, x, when, *, visible=True):
    pos = dict(sampled_at=when, age_seconds=10-when, xz=[x, 0])
    return add_fact(frame, 'vision_fact_ids', entity='entity:'+actor, field='observer_visibility',
                    value=dict(team_id=100, visible=visible, last_observed_position=pos),
                    unit=None, scope='queried_at_decision_time', when=10)


def ally_path(frame, actor, x, when):
    return add_fact(frame, 'allied_path_fact_ids', entity=actor, field='allied_path_start_sample',
                    value=dict(observer_team_id=100, xz=[x, 0]), unit='map11_world_xz',
                    scope='historical_path_start_sample', when=when)


def review(b):
    return review_round_plan(freeze(b))['support_lane_opportunity']


def test_fresh_geometry_changes_which_opponent_to_check_before_leaving():
    b = lane_case()
    f = b['frame']
    ally = ally_path(f, 'ally', 100, 9.9)
    ally_path(f, 'self', 600, 9.7)
    kog = seen(f, 'enemy', 710, 9.8)
    yi = seen(f, 'jungler', 251, 9.9)
    seen(f, 'tahm', 110, 9.95, visible=False)
    o = review(b)
    assert o['observations']['geometry']['support_to_enemy_carry']['sampled_gap_world_units'] == 110
    env = o['observations']['opponents_near_carry']
    assert env['by_sampled_gap'] == [
        dict(entity_id='jungler', champion='MasterYi', sampled_gap_world_units=151,
             sampled_at_seconds=[9.9, 9.9], fact_refs=[ally, yi]),
        dict(entity_id='enemy', champion='KogMaw', sampled_gap_world_units=610,
             sampled_at_seconds=[9.9, 9.8], fact_refs=[ally, kog])]
    assert env['without_recent_pair'] == ['tahm']
    assert o['engage']['common_target_window'] == 'unknown'
    assert o['observations']['geometry']['enemy_support_to_enemy_carry'] is None
    assert o['matchup']['cast_readiness'] is None
    # Same geometry, but the teammate's path start can no longer ground a current comparison.
    f['allied_path_fact_ids'].remove(ally)
    ally_path(f, 'ally', 100, 8.99)
    assert review(b)['observations']['opponents_near_carry']['by_sampled_gap'] == []


@pytest.mark.parametrize(('when', 'level', 'visible', 'phase'), [
    (10, 5, True, 'below_six_observed'), (10, 6, True, 'six_or_higher_observed'),
    (9.9, 5, True, 'unknown'), (10, 5, False, 'unknown')])
def test_tahm_phase_depends_on_current_visible_level(when, level, visible, phase):
    b = lane_case()
    f = b['frame']
    seen(f, 'tahm', 0, when, visible=visible)
    fid = add_fact(f, 'test_facts', entity='tahm', field='level', value=level, unit=None,
                   scope='observed_sample', when=when)
    next(h for h in f['lineup'] if h['entity_id'] == 'tahm')['current_fact_ids'].append(fid)
    match = review(b)['matchup']
    assert match['tahm_level_phase'] == phase
    assert match['tahm_level_fact_ref'] == (fid if visible else None)
    assert match['enemy_rescue_ready'] is None
    assert match['sources']['TahmKench']['url'].endswith('/16.22.1/data/zh_CN/champion/TahmKench.json')


def test_bound_destination_and_bottom_wave_cost_use_only_matching_clocks():
    b = lane_case()
    f = b['frame']
    ids = {}
    for key, span in [('route_duration', [3, 4]), ('target_work_duration', [2, 3]),
                      ('return_duration', [3, 4]), ('next_wave_deadline', [19, 20])]:
        ids[key] = clock(f, key, span, lane='bot', target='river_entrance', when=10)
    clock(f, 'target_deadline', [100, 100], target='dragon', lane='bot', when=10)
    wave_ref = add_fact(f, 'lane_fact_ids', field='lane_current_units_and_groups', entity='lane:bot',
                        value=dict(lane='bot', count_scope='own_team_observed_live_only',
                                   counts=[dict(team_id=100, kind='melee', count=3)]),
                        scope='queried_at_decision_time', unit=None, when=10)
    out = review(b)
    roam = out['roam']
    assert roam['clock_fact_refs'] == ids and roam['wave_evidence_id'] == wave_ref
    assert roam['destination'] == 'river_entrance' and roam['wave_number'] is None
    assert out['observations']['bottom_wave']['enemy_minions']['observed_count'] is None
    now, after_help, after_clear = roam['timing_options']
    assert now['return_to_lane_at'] == [18, 21] and now['next_wave_window'] == 'overlap'
    assert after_help['next_wave_window'] == 'too_late' and after_clear['depart_at'] is None
    assert [r['return_margin_seconds'] for r in roam['timing_options']] == [[-2, 2], [-5, -1], None]
    assert all(row['target_window'] == 'unknown' for row in roam['timing_options'])


@pytest.mark.parametrize('kwargs', [{'build':'16.21'}, {'carry':'Ashe'}])
def test_other_duos_and_patches_get_no_matchup_specific_claims(kwargs):
    b = lane_case(**kwargs)
    lane = review(b)
    assert lane['matchup'] is None
    assert lane['engage']['matchup_if'] is None and lane['hold']['matchup_if'] is None
    assert lane['roam']['destination'] == 'river_entrance'
    unbound = deepcopy(b)
    del unbound['frame']['task']['bottom_lane_review']
    assert 'support_lane_opportunity' not in review_round_plan(freeze(unbound))


def test_wrong_role_binding_fails_closed():
    b = lane_case()
    b['frame']['task']['bottom_lane_actors']['carry'] = 'tahm'
    with pytest.raises(ValueError, match='invalid_bottom_lane_actors'):
        review(b)


def destination_case():
    bundle = lane_case()
    f = bundle['frame']
    for entity, relation, champ in [('ours_jg', 'ally', 'Braum'), ('ours_mid', 'ally', 'Soraka'),
                                    ('their_mid', 'enemy', 'Garen')]:
        f['lineup'].append(dict(entity_id=entity, champion=champ, relation=relation,
                                current_fact_ids=[], history_fact_ids=[]))
    f['task']['roam_actors'] = dict(ally_jungle='ours_jg', ally_mid='ours_mid',
                                   enemy_mid='their_mid', enemy_jungle='jungler')
    return bundle


def test_destinations_separate_mid_and_jungle_with_verified_roles_and_static_terrain():
    b = destination_case()
    f = b['frame']
    ally_path(f, 'self', 700, 9.9)
    ally_path(f, 'ally', 1200, 9.9)
    mid_id = ally_path(f, 'ours_mid', 7000, 9.9)
    jg_id = ally_path(f, 'ours_jg', 9500, 9.9)
    their_mid = seen(f, 'their_mid', 8000, 9.9)
    seen(f, 'jungler', 1120, 9.9, visible=False)
    ward = add_fact(f, 'vision_fact_ids', entity='entity:ward1', field='allied_ward_last_sample',
                    value=dict(family='control_ward', sampled_at=7, xz=[10500, 5000]), unit=None,
                    scope='last_position_no_removal_observed_by_cutoff', when=7)
    def compare():
        return review(b)['destination_comparison']
    dc = compare()
    assert set(dc['candidates']) == {'hold_bot','river_jungle','mid_lane'}
    assert dc['actors']['ally_mid']['champion'] == 'Soraka'
    river = dc['candidates']['river_jungle']
    mid = dc['candidates']['mid_lane']
    assert mid_id in mid['fact_refs'] and their_mid in mid['fact_refs'] and jg_id not in mid['fact_refs']
    assert jg_id in river['fact_refs'] and ward in river['fact_refs']
    assert mid['geometry']['mid_pair']['sampled_gap_world_units'] == 1000
    assert mid['geometry']['enemy_jungle_to_ally_mid'] is None
    assert mid['geometry']['mid_outer_towers']['sample_distances']['ally_mid']['fact_id'] == mid_id
    rc = river['geometry']['lower_river']
    assert rc['static_reference']['locator'] == 'DragonEelCamp'
    assert 'enemy_jungle' not in rc['sample_distances']
    assert rc['nearest_registered_ward']['sampled_gap_world_units'] == 170
    # Turn off the exact same target's visibility: cancel prospective gank geometry,
    # retain the ability to propose a countergank/defense as a conditional option.
    f['vision_fact_ids'].remove(their_mid)
    seen(f, 'their_mid', 8000, 9.9, visible=False)
    now = compare()['candidates']['mid_lane']
    assert now['geometry']['mid_pair'] is None
    assert 'enemy_mid' not in now['geometry']['mid_outer_towers']['sample_distances']
    assert '反蹲' in now['marginal_gain_if']


def test_destination_timing_does_not_borrow_dragon_or_other_route_or_player():
    b = destination_case()
    f = b['frame']
    f['task']['round_comparison']['target'] = 'dragon'
    f['task']['round_comparison']['help_seconds'] = 3
    for dest, travel in [('dragon', 1), ('mid_lane', 18), ('river_jungle', 5)]:
        for key, val in [('route_duration', travel), ('target_work_duration', 4),
                         ('return_duration', 9), ('next_wave_deadline', 38)]:
            clock(f, key, [val, val], target=dest, lane='bot', when=10)
    clock(f, 'target_deadline', [30,30], entity='ours_mid', target='mid_lane', lane='bot', when=10)
    c = review(b)['destination_comparison']['candidates']
    assert c['mid_lane']['timing']['leave_now']['return_to_lane_at'] == [41,41]
    assert c['mid_lane']['timing']['leave_now']['next_wave_window'] == 'too_late'
    assert c['river_jungle']['timing']['leave_now']['return_to_lane_at'] == [28,28]
    assert c['river_jungle']['timing']['leave_now']['next_wave_window'] == 'before_or_at'
    assert c['mid_lane']['timing']['leave_now']['target_window'] == 'unknown'
    assert c['hold_bot']['timing'] is None


def test_closer_carry_opponent_changes_cost_and_hidden_or_stale_is_unknown():
    b = destination_case()
    f = b['frame']
    ally_path(f, 'self', 700, 9.99)
    ally_path(f, 'ally', 1200, 9.99)
    sight = None
    for x, when, visible, expected in [(2000, 9.99, True, False), (1210, 9.99, True, True),
                                       (1210, 9.99, False, None), (1210, 8.95, True, None)]:
        if sight:
            f['vision_fact_ids'].remove(sight)
        sight = seen(f, 'jungler', x, when, visible=visible)
        gate = review(b)['destination_comparison']['bottom_gate']
        assert gate['opponent_sample_closer_than_support'] is expected


def test_partial_assignment_never_fills_mid_by_champion_or_reuses_a_duo_member():
    b = destination_case()
    roles = b['frame']['task']['roam_actors']
    del roles['ally_mid']
    mid = review(b)['destination_comparison']['candidates']['mid_lane']
    assert 'ally_mid' in mid['unassigned_roles']
    assert 'ally_mid' not in mid['actor_ids'] and mid['geometry']['mid_pair'] is None
    roles['ally_mid'] = ROLES['carry']
    with pytest.raises(ValueError, match='invalid_roam_actors'):
        review(b)


def test_top_fight_deadline_changes_before_arrival_without_affecting_mid_or_confirming_a_ward():
    b = destination_case()
    f = b['frame']
    for actor, team in [('our_top','ally'),('their_top','enemy')]:
        f['lineup'].append(dict(entity_id=actor, champion='Gnar', relation=team,
                                current_fact_ids=[], history_fact_ids=[]))
    f['task']['roam_actors'].update(ally_top='our_top', enemy_top='their_top')
    own = ally_path(f, 'our_top', 3500, 9.9)
    foe = seen(f, 'their_top', 4000, 9.9)
    clock(f, 'route_duration', [24,26], target='top_lane', lane='bot', when=10)
    deadline = clock(f, 'target_deadline', [40,40], target='top_lane', lane='bot', when=10)
    c = review(b)['destination_comparison']['candidates']
    first = c['top_lane']
    assert {own, foe} <= set(first['fact_refs'])
    assert first['geometry']['top_pair']['sampled_gap_world_units'] == 500
    assert first['timing']['leave_now']['target_window'] == 'before_or_at'
    f['timing_fact_ids'].remove(deadline)
    clock(f, 'target_deadline', [32,32], target='top_lane', lane='bot', when=10)
    changed = review(b)['destination_comparison']['candidates']
    top = changed['top_lane']
    assert top['timing']['leave_now']['target_window'] == 'too_late'
    assert '有眼' in top['if_fight_ends_before_arrival'] and '回线' in top['if_fight_ends_before_arrival']
    assert top['timing']['leave_now']['return_to_lane_at'] is None
    assert changed['mid_lane'] == c['mid_lane']


@pytest.mark.parametrize(('support', 'age', 'x', 'in_range'), [
    ('Pantheon', 0.1, 5500, True), ('Pantheon', 0.1, 5500.04, False),
    ('Pantheon', 2, 1000, None), ('Rakan', 0.1, 1000, None)])
def test_roam_mobility_compares_only_sampled_ally_with_static_range(support, age, x, in_range):
    b = destination_case()
    frame = b['frame']
    next(row for row in frame['lineup'] if row['entity_id'] == 'self')['champion'] = support
    ally_path(frame, 'self', 0, 10 - age)
    ally_path(frame, 'ours_mid', x, 10)
    geometry = review(b)['destination_comparison']['candidates']['mid_lane']['geometry']
    if support == 'Rakan':
        assert 'pantheon_r_to_ally_sample' not in geometry
        return
    mobility = geometry['pantheon_r_to_ally_sample']
    assert mobility['ally_sample_within_range'] is in_range
    assert mobility['ready'] is None and mobility['observed_cast'] is None
