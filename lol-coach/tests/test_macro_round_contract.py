"""Synthetic scope/continuity checks. The validator does not grade map tactics."""
from copy import deepcopy

import pytest

from lol_coach.decision_contract import output_schema, render_decision, validate_decision
from lol_coach.reasoning_frame import model_messages
from lol_coach.round_chain import attach_previous_plan
from lol_coach.round_model_format import expand_round_response, prepare_round_request
from lol_coach.round_tools import ROUND_TOOLS, bind_round
from test_round_agent_integration import round_answer
from test_round_chain import bundle_at, freeze
from test_round_model_format import data, record


def bound(at, **kwargs):
    return bind_round(bundle_at(at, **kwargs), 'mid', 'dragon', 5, macro_review=True)


def card(bundle, transition='start'):
    seed = deepcopy(bundle)
    seed['frame']['task'].pop('macro_round_review')
    answer = round_answer(seed)
    answer['macro_round'] = dict(
        transition=transition, intent='pressure', map_goal='先保中线，再看河道是否可进。',
        enabling_condition='若这波能先推完，可从河口给压力。', opponent_reply='对方可能绕过河口抢先落位。',
        fact_refs=['gold'], change_refs=[],
    )
    return answer


def test_tag_enables_only_new_answers_and_keeps_uncertain_boundary_honest():
    b = bound(10)
    answer = card(b)
    old = bind_round(bundle_at(10), 'mid', 'dragon', 5)
    assert 'macro_round' not in output_schema(old['frame'])['properties']
    assert validate_decision(round_answer(old), old['frame'])['status'] == 'PASS'
    assert validate_decision(answer, b['frame'])['status'] == 'PASS'
    del answer['macro_round']
    assert validate_decision(answer, b['frame'])['status'] == 'FAIL'
    answer = card(b, 'continue')
    assert validate_decision(answer, b['frame'])['status'] == 'FAIL'
    answer['macro_round'].update(transition='unknown', intent='unknown')
    assert validate_decision(answer, b['frame'])['status'] == 'PASS'


def test_macro_plan_survives_route_or_target_change_without_fabricated_execution():
    old = bound(10)
    current = attach_previous_plan(bound(20, tower_health=0), old, card(old))
    plan = current['frame']['task']['previous_plan']
    prior_macro = plan['decision_card']['macro_round']
    assert plan['execution_status'] == 'unknown'
    assert prior_macro['fact_refs'] == ['h_gold'] and 'change_refs' not in prior_macro
    answer = card(current, 'continue')
    answer['macro_round']['map_goal'] = '若中路线权仍在，可将压力转到对面下半野区。'
    assert validate_decision(answer, current['frame'])['status'] == 'PASS'
    answer['macro_round']['transition'] = 'start'
    assert validate_decision(answer, current['frame'])['status'] == 'FAIL'
    answer['macro_round'].update(transition='close', intent='defend')
    assert validate_decision(answer, current['frame'])['status'] == 'FAIL'
    change_id = next(k for k, v in current['frame']['task']['round_transition']['changes'].items()
                     if v['current_fact_id'] == 'tower_hp')
    answer['macro_round']['change_refs'] = [change_id]
    assert validate_decision(answer, current['frame'])['status'] == 'FAIL'
    answer['macro_round']['fact_refs'] = ['tower_hp']
    assert validate_decision(answer, current['frame'])['status'] == 'FAIL'
    answer['facts_used'].append(dict(fact_id='tower_hp', value=0))
    assert validate_decision(answer, current['frame'])['status'] == 'PASS'
    answer['macro_round']['fact_refs'] = ['h_tower_hp']
    assert validate_decision(answer, current['frame'])['status'] == 'FAIL'


def test_only_an_older_age_of_the_same_sighting_cannot_close_map_plan():
    old, current = bound(10), bound(20)
    for bundle in (old, current):
        frame = bundle['frame']
        at = frame['decision']['at_seconds']
        frame['facts']['vision'] = dict(entity_id='enemy', field='observer_visibility', observed_at_seconds=5,
            temporal_scope='queried_at_decision_time', value=dict(visible=False, team_id=100,
                last_observed_position=dict(sampled_at=5, xz=[10, 20], age_seconds=at-5)))
        freeze(bundle)
    linked = attach_previous_plan(current, old, card(old))
    changes = linked['frame']['task']['round_transition']['changes']
    assert not any(c['current_fact_id'] == 'vision' for c in changes.values())
    # An already saved pre-filter transition may still contain that difference.
    frame = linked['frame']
    frame['task']['previous_plan']['historical_facts']['h_vision'] = old['frame']['facts']['vision']
    changes['old_age'] = dict(current_fact_id='vision', historical_fact_id='h_vision')
    answer = card(linked, 'close')
    answer['macro_round'].update(fact_refs=['vision'], change_refs=['old_age'])
    answer['facts_used'].append(dict(fact_id='vision', value=frame['facts']['vision']['value']))
    assert validate_decision(answer, frame)['status'] == 'FAIL'
    frame['facts']['vision']['value']['visible'] = True
    assert validate_decision(answer, frame)['status'] == 'PASS'


def test_macro_intent_remains_readable_when_three_conditional_routes_are_unranked():
    b = bound(10)
    answer = card(b)
    answer['macro_round']['intent'] = 'trade'
    answer['recommendation'].update(preferred_option_id=None, fallback_option_id=None,
                                    confidence='insufficient_evidence')
    check = validate_decision(answer, b['frame'])
    assert check['status'] == 'PASS'
    text = render_decision(answer, check)
    for segment in ('提出本轮计划', '交换资源', '## 接下来怎么选', '现有信息不足以为你选定首选',
                    answer['macro_round']['enabling_condition'], answer['macro_round']['opponent_reply']):
        assert segment in text


@pytest.mark.parametrize(('plan_uses_pit', 'observed_at', 'heading'), [
    (False, 10, '接下来怎么选'),
    (True, 9, '接下来怎么选'),
    (True, 10, '小龙在场时怎么选'),
])
def test_dragon_route_clock_does_not_set_the_subject_of_the_card(plan_uses_pit, observed_at, heading):
    bundle = bound(10)
    frame = bundle['frame']
    frame['facts']['pit'] = dict(entity_id='dragon-pit', field='dragon_pit_observation',
        value={'alive': True}, observed_at_seconds=observed_at, temporal_scope='player_view_at_video_frame')
    answer = card(freeze(bundle))
    answer['macro_round']['map_goal'] = '下路接应队友。'
    if plan_uses_pit:
        answer['macro_round'].update(map_goal='争夺坑内的亚龙。', fact_refs=['pit'])
        answer['facts_used'].append(dict(fact_id='pit', value={'alive': True}))
    check = validate_decision(answer, frame)
    assert check['status'] == 'PASS'
    assert '## ' + heading in render_decision(answer, check).splitlines()


def test_close_a_live_pit_cannot_substitute_a_players_health_for_public_confirmation():
    old, new = bound(10), bound(20)
    for bundle in (old, new):
        bundle['frame']['facts']['ownhp'] = dict(entity_id='self', field='health',
            value=bundle['frame']['decision']['at_seconds'] * 5,
            temporal_scope='observed_sample', observed_at_seconds=bundle['frame']['decision']['at_seconds'] - 1)
    old['frame']['facts']['pit'] = dict(entity_id='dragon-pit', field='dragon_pit_observation',
        value='龙坑内亚龙仍存活，目标与本人同屏。', observed_at_seconds=9, temporal_scope='player_view_at_video_frame')
    new['frame']['facts']['announce'] = dict(entity_id='self', field='allied_dragon_kill',
        value={'name_from_announcement': 'Cloud Drake'}, observed_at_seconds=18, available_at_seconds=19,
        temporal_scope='historical_replay_event_cross_checked_by_player_HUD')
    first = card(freeze(old))
    first['macro_round']['fact_refs'] = ['pit']
    first['facts_used'].append(dict(fact_id='pit', value=old['frame']['facts']['pit']['value']))
    current = attach_previous_plan(freeze(new), old, first)
    answer = card(current, 'close')
    frame = current['frame']
    by_fact = {v['current_fact_id']: k for k, v in frame['task']['round_transition']['changes'].items()}
    for fid, expected in [('ownhp', 'FAIL'), ('announce', 'PASS')]:
        answer['facts_used'].append(dict(fact_id=fid, value=frame['facts'][fid]['value']))
        answer['macro_round'].update(fact_refs=[fid], change_refs=[by_fact[fid]])
        assert validate_decision(answer, frame)['status'] == expected
    # The event is contemporaneous but independent of a plan to defend mid.
    first['macro_round'].update(intent='defend', map_goal='守中塔', fact_refs=['gold'])
    other = attach_previous_plan(new, old, first)
    answer = card(other, 'close')
    answer['facts_used'].append(dict(fact_id='ownhp', value=frame['facts']['ownhp']['value']))
    answer['macro_round'].update(fact_refs=['ownhp'], change_refs=[by_fact['ownhp']])
    assert validate_decision(answer, other['frame'])['status'] == 'PASS'


def test_local_first_frame_obtains_macro_evidence_before_emitting_the_formatted_card():
    b = bound(10)
    schema = output_schema(b['frame'])
    req = dict(messages=model_messages(b, schema), tools=ROUND_TOOLS, response_schema=schema)
    record(req, 'compare_round_options')
    with pytest.raises(ValueError, match='required_round_tools_missing_at_final_call'):
        prepare_round_request(req, remaining_calls=1)
    record(req, 'review_round_plan', 'q2')
    _, fmt = prepare_round_request(req, remaining_calls=1)
    branches = fmt['properties']['answer']['properties']['macro_round']['anyOf']
    assert {obj['properties']['transition']['enum'][0] for obj in branches} == {'start', 'unknown'}
    answer = card(b)
    assert expand_round_response(req, data(answer)) == {'answer': answer}
