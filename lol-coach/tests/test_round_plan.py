"""Condition flips and unknowns on synthetic frozen frames, using the real plan linker."""
from copy import deepcopy

import pytest

from lol_coach.reasoning_frame import digest
from lol_coach.round_chain import attach_previous_plan
from lol_coach.round_plan import review_round_plan
from test_round_chain import answer_for, bundle_at, freeze


def add_fact(bundle, actor, field, value, t, scope):
    fact = dict(entity_id=actor, field=field, value=value, temporal_scope=scope,
                observed_at_seconds=t, age_seconds=bundle['frame']['decision']['at_seconds']-t)
    fid = 'f_' + digest(fact)[:20]
    bundle['frame']['facts'][fid] = fact
    freeze(bundle)
    return fid


def with_vision(bundle, visible, sampled_at):
    value = dict(visible=visible, team_id=100)
    fid = add_fact(bundle, 'entity:enemy', 'observer_visibility', value,
                   sampled_at, 'queried_at_decision_time')
    bundle['frame']['vision_fact_ids'] = [fid]
    freeze(bundle)
    return fid


def answer(old):
    result = answer_for(old)
    result['options'][0]['ally_requirements'][0]['action_key'] = 'move_to_entry'
    result['options'][1]['ally_requirements'] = []
    return result


def kill(bundle, when):
    fid = add_fact(bundle, 'ally', 'public_kill_feed',
                   dict(victim_entity_id='ally', killer_entity_id='enemy'),
                   when, 'historical_event_not_current_death_state')
    bundle['frame'].setdefault('recent_public_combat_ids', []).append(fid)
    freeze(bundle)
    return fid


def test_standalone_has_no_prior_plan_or_known_engagement_timing():
    bundle = bundle_at(20)
    before = deepcopy(bundle)
    result = review_round_plan(bundle)
    assert result['status'] == 'no_previous_plan' and result['prior_frame_id'] is None
    assert result['engagement']['first_effect_on_common_target_seconds'] is None
    assert result['engagement']['shared_enemy_area_hit'] is None
    assert result['allies'][0]['commitment'] == 'unknown'
    assert result['triggers'] == [] and bundle == before


@pytest.mark.parametrize(('before', 'after', 'expected'), [
    (False, True, 'enemy_reappeared'), (True, False, 'enemy_left_vision'),
    (None, True, 'enemy_visibility_evidence_changed'), (True, None, 'enemy_visibility_evidence_changed'),
    (False, False, None)])
def test_visibility_changes_have_two_bound_evidence_ids(before, after, expected):
    old, cur = bundle_at(10), bundle_at(20)
    old_id, new_id = with_vision(old, before, 9), with_vision(cur, after, 18)
    linked = attach_previous_plan(cur, old, answer(old))
    report = review_round_plan(linked)
    if expected is None:
        assert report['status'] == 'monitor'
        assert report['triggers'] == []
    else:
        trigger, = report['triggers']
        assert report['status'] == 'reopen'
        assert trigger['kind'] == expected
        assert trigger['scope'] == 'general_review' and trigger['option_ids'] == []
        assert (trigger['previous_fact_id'], trigger['current_fact_id']) == ('h_' + old_id, new_id)
        assert trigger['change_id'] in linked['frame']['task']['round_transition']['changes']
    assert report['previous_action_execution'] == 'unknown'


@pytest.mark.parametrize(('option_index', 'in_ally_requirement', 'status'), [
    (1, False, 'monitor'), (0, False, 'reopen'), (0, True, 'reopen')])
def test_visibility_change_targets_options_that_cited_the_previous_sighting(option_index, in_ally_requirement, status):
    old, cur = bundle_at(10), bundle_at(20)
    old_id = with_vision(old, False, 9)
    new_id = with_vision(cur, True, 18)
    old_card = answer(old)
    option = old_card['options'][option_index]
    evidence = option['ally_requirements'][0] if in_ally_requirement else option
    evidence['fact_refs'].append(old_id)
    report = review_round_plan(attach_previous_plan(cur, old, old_card))
    trigger, = report['triggers']
    assert report['status'] == status
    assert trigger['scope'] == 'prior_options'
    assert trigger['option_ids'] == [option['id']]
    assert (trigger['previous_fact_id'], trigger['current_fact_id']) == ('h_' + old_id, new_id)


def test_repeated_public_kill_of_required_ally_reopens_even_when_value_equal():
    old, cur = bundle_at(10), bundle_at(20)
    kill(old, 3)
    new_death = kill(cur, 14)
    linked = attach_previous_plan(cur, old, answer(old))
    report = review_round_plan(linked)
    trigger, = report['triggers']
    assert report['status'] == 'reopen' and trigger['current_fact_id'] == new_death
    assert trigger['kind'] == 'required_ally_killed'
    assert trigger['option_ids'] == ['a'] and trigger['change_id'] is None
    assert report['allies'][0]['requirements'][0]['evidence_status'] == 'interrupted_recheck_availability'
    assert 'currently_dead' not in report['allies'][0]


def test_prior_kill_or_new_irrelevant_ally_action_does_not_reopen():
    old, cur = bundle_at(10), bundle_at(20)
    kill(cur, 9)
    add_fact(cur, 'ally', 'action_observation', dict(action_key='other', status='completed'),
             13, 'observed_action')
    report = review_round_plan(attach_previous_plan(cur, old, answer(old)))
    assert report['status'] == 'monitor'
    assert report['allies'][0]['requirements'][0]['evidence_status'] == 'unconfirmed'


def test_only_matching_actor_action_observed_after_interruption_restores_evidence():
    old, cur = bundle_at(10), bundle_at(20)
    value = dict(action_key='move_to_entry', status='in_progress')
    add_fact(cur, 'ally', 'action_observation', value, 12, 'observed_action')
    add_fact(cur, 'enemy', 'action_observation', value, 16, 'observed_action')
    kill(cur, 14)
    first = review_round_plan(attach_previous_plan(cur, old, answer(old)))
    assert first['allies'][0]['requirements'][0]['evidence_status'] == 'interrupted_recheck_availability'
    new_id = add_fact(cur, 'ally', 'action_observation', value, 17, 'observed_action')
    second = review_round_plan(attach_previous_plan(cur, old, answer(old)))
    need, = second['allies'][0]['requirements']
    assert need['evidence_status'] == 'matching_action_observed' and need['fact_id'] == new_id
    assert second['allies'][0]['commitment'] == 'unknown'


def test_enemy_visible_in_native_channel_wins_over_legacy_channel():
    old, cur = bundle_at(10), bundle_at(20)
    with_vision(old, False, 9)
    with_vision(cur, False, 18)
    for bundle, flag in [(old, False), (cur, True)]:
        fid = add_fact(bundle, 'enemy', 'visibility', flag, 8, 'visibility_policy')
        bundle['frame']['lineup'][2]['current_fact_ids'].append(fid)
        freeze(bundle)
    assert review_round_plan(attach_previous_plan(cur, old, answer(old)))['status'] == 'monitor'


def test_lane_count_changes_only_reopen_an_option_that_used_that_lane():
    def lane(bundle, count):
        return add_fact(bundle, 'lane:middle', 'lane_current_units_and_groups',
                        dict(counts=[dict(team_id=100, kind='caster', count=count)]),
                        bundle['frame']['decision']['at_seconds'], 'observer_limited')
    old, cur = bundle_at(10), bundle_at(20)
    fid = lane(old, 2)
    lane(cur, 1)
    old_answer = answer(old)
    assert review_round_plan(attach_previous_plan(cur, old, old_answer))['status'] == 'monitor'
    old_answer['options'][0]['fact_refs'].append(fid)
    report = review_round_plan(attach_previous_plan(cur, old, old_answer))
    signal, = report['triggers']
    assert signal['kind'] == 'observed_lane_counts_changed' and signal['option_ids'] == ['a']


def test_future_evidence_rejected_before_it_enters_plan():
    cur = bundle_at(20)
    kill(cur, 21)
    with pytest.raises(ValueError, match='future_or_invalid_fact_time'):
        review_round_plan(cur)


def engagement_bundle(ally_first=(2, 3), ally_x=60, outcomes=None):
    bundle = bundle_at(20)
    with_vision(bundle, True, 19)
    f = bundle['frame']
    f['task']['engagement_question'] = dict(ally_id='ally', target_id='enemy',
                                            enemy_area_source_id='enemy', enemy_area_cast_id='cast-A')
    f['engagement_fact_ids'] = []
    def record(actor, kind, **value):
        if kind in ('first_effect', 'control_window'):
            scope = 'conditional_engagement_at_decision'
            value['target_id'] = 'enemy'
        else:
            scope = 'observed_engagement_at_decision'
            value.update(source_id='enemy', cast_id='cast-A')
        fid = add_fact(bundle, actor, 'round_engagement_input',
                       dict(kind=kind, observer_team_id=100, **value), 20, scope)
        f['engagement_fact_ids'].append(fid)
    record('self', 'first_effect', interval_seconds=[0.8, 1.2])
    record('ally', 'first_effect', interval_seconds=list(ally_first))
    record('enemy', 'control_window', interval_seconds=[0, 3])
    record('self', 'actor_disc', xz=[0, 0], radius_world_units=10, coordinate_space='map_world_xz')
    record('ally', 'actor_disc', xz=[ally_x, 0], radius_world_units=10, coordinate_space='map_world_xz')
    record('enemy', 'cast_disc', xz=[0, 0], radius_world_units=50, coordinate_space='map_world_xz')
    if outcomes is not None:
        record('enemy', 'cast_result', outcomes=outcomes)
    return freeze(bundle)


@pytest.mark.parametrize(('arrival', 'expected'), [
    ((2, 3), 'both_within_window'), ((3, 4), 'overlap_uncertain'),
    ((3.1, 4), 'first_effect_outside_window')])
def test_actor_specific_effects_and_inclusive_control_window(arrival, expected):
    result = review_round_plan(engagement_bundle(arrival))['engagement']
    assert result['support_window'] == expected
    assert result['first_effect_on_common_target_seconds']['ally'] == list(arrival)
    assert result['control_window_seconds'] == [0, 3]


def test_separating_allies_changes_area_coverage_without_delaying_their_effect():
    near = review_round_plan(engagement_bundle(ally_x=60))['engagement']
    far = review_round_plan(engagement_bundle(ally_x=60.1))['engagement']
    assert near['shared_enemy_area_coverage'] == dict(covered_actor_ids=['self', 'ally'], both=True)
    assert far['shared_enemy_area_coverage'] == dict(covered_actor_ids=['self'], both=False)
    assert near['support_window'] == far['support_window'] == 'both_within_window'
    assert near['shared_enemy_area_hit'] is far['shared_enemy_area_hit'] is None


@pytest.mark.parametrize(('outcomes','expected'), [
    ({'self':'hit','ally':'hit'}, True), ({'self':'hit','ally':'miss'}, False), ({'self':'hit'}, None)])
def test_one_shared_cast_requires_both_observed_results(outcomes, expected):
    result = review_round_plan(engagement_bundle(outcomes=outcomes))['engagement']
    assert result['shared_enemy_area_hit'] is expected


@pytest.mark.parametrize(('index','field','expected'), [
    (1,'support_window','unknown'), (2,'support_window','unknown'),
    (4,'shared_enemy_area_coverage',None), (5,'shared_enemy_area_coverage',None)])
def test_removing_one_decisive_fact_restores_only_its_unknown(index, field, expected):
    bundle = engagement_bundle()
    del bundle['frame']['engagement_fact_ids'][index]
    result = review_round_plan(freeze(bundle))['engagement']
    assert result[field] == expected
    if field == 'support_window':
        assert result['shared_enemy_area_coverage']['both']
    else:
        assert result['support_window'] == 'both_within_window'


def test_unknown_or_wrong_target_cannot_support_forecast():
    bundle = engagement_bundle()
    with_vision(bundle, False, 20)
    result = review_round_plan(bundle)['engagement']
    assert result['support_window'] == 'unknown'
    assert result['first_effect_on_common_target_seconds'] is None
    bundle['frame']['task']['engagement_question']['target_id'] = 'ally'
    with pytest.raises(ValueError, match='invalid_engagement_participants'):
        review_round_plan(freeze(bundle))


def test_engagement_forecast_cannot_reuse_another_teams_observation():
    bundle = engagement_bundle()
    f = bundle['frame']
    other = deepcopy(f['facts'][f['engagement_fact_ids'][0]])
    other['value']['observer_team_id'] = 200
    fid = 'f_' + digest(other)[:20]
    f['facts'][fid] = other
    f['engagement_fact_ids'][0] = fid
    with pytest.raises(ValueError, match='invalid_engagement_evidence_scope'):
        review_round_plan(freeze(bundle))
