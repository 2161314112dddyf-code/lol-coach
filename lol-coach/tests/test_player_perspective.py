"""The recipient and the actor for every recommendation must be the selected player."""
from copy import deepcopy

import pytest

from lol_coach.decision_contract import output_schema, render_decision, review_scope, validate_decision
from test_decision_contract import answer_fixture, frame_fixture


def player_case():
    frame = frame_fixture()
    frame['task'] = {'player_perspective': {
        'player_entity_id': 'self', 'champion': 'A', 'observer_team_id': 100}}
    answer = answer_fixture()
    answer['immediate_action'] = '先向安全方向靠一步，观察入口。'
    for option in answer['options']:
        option['actor_id'] = 'self'
    return frame, answer


@pytest.mark.parametrize('other', ['ally', 'enemy', None])
def test_same_team_or_enemy_cannot_be_substituted_into_a_player_choice(other):
    frame, answer = player_case()
    if other is None:
        del answer['options'][1]['actor_id']
    else:
        answer['options'][1]['actor_id'] = other
    check = validate_decision(answer, frame)
    assert check['status'] == 'FAIL'
    assert '$.options[1].actor_id' in [e['path'] for e in check['errors']]
    assert '你的备选' not in render_decision(answer, check)


@pytest.mark.parametrize('change', [{'observer_team_id': 200}, {'champion': 'B'}, {'player_entity_id': 'ally'}])
def test_tag_must_match_player_roster_and_observer(change):
    frame, answer = player_case()
    frame['task']['player_perspective'].update(change)
    check = validate_decision(answer, frame)
    assert check['status'] == 'FAIL' and 'player_perspective' not in check


def test_legacy_shape_and_tagged_player_schema():
    frame, answer = player_case()
    schema = output_schema(frame)
    assert 'actor_id' in schema['properties']['options']['items']['required']
    assert 'immediate_action' in schema['required']
    assert 'immediate_action' not in output_schema()['properties']
    assert validate_decision(answer_fixture(), frame_fixture())['status'] == 'PASS'
    del answer['immediate_action']
    assert validate_decision(answer, frame)['status'] == 'FAIL'


def test_verified_player_can_receive_a_card_without_a_known_champion_name():
    frame, answer = player_case()
    frame['task']['player_perspective']['champion'] = frame['lineup'][0]['champion'] = None
    validation = validate_decision(answer, frame)
    assert validation['status']=='PASS'
    assert 'self' in render_decision(answer, validation).splitlines()[0]


def test_same_champion_on_two_replays_has_distinct_visible_source_and_mode():
    frame, answer = player_case()
    frame['lineup'][0]['champion'] = frame['task']['player_perspective']['champion'] = 'Pantheon'
    match = {'frame': frame, 'audit': {'source_replay_sha256': 'b'*64}}
    practice = deepcopy(match)
    practice['frame']['decision'].update(map_mode='practice_tool',
                                         environment_status='practice_tool_controls_on_player_screen')
    practice['audit']['source_replay_sha256'] = 'a'*64
    frame['lineup'].extend({'entity_id': 'actor'+str(i), 'relation': 'enemy', 'champion': 'Other'}
                           for i in range(7))
    label = review_scope(practice, 'TEST-1')
    assert label == '回放 TEST-1 · 训练模式 · 选定视角为蓝方 Pantheon'
    card = render_decision(answer, validate_decision(answer, practice['frame']), review_scope_label=label)
    assert label in card.splitlines()[:4]
    assert review_scope(match) == '回放 SHA-256 ' + 'b'*64 + ' · 十人阵容 · 选定视角为蓝方 Pantheon'


def test_player_still_gets_an_immediate_action_when_no_route_is_ranked():
    frame, answer = player_case()
    answer['recommendation'].update(preferred_option_id=None, fallback_option_id=None,
                                    confidence='insufficient_evidence')
    check = validate_decision(answer, frame)
    assert check['status'] == 'PASS'
    card = render_decision(answer, check)
    assert '00:10 · 你的 A 复盘' in card
    assert card.index(answer['immediate_action']) < card.index('不足以为你选定首选')
    assert '当前事实引用' not in card


def test_player_reads_counterplay_and_exit_for_the_chosen_route_only():
    frame, answer = player_case()
    first, second = answer['options']
    first.update(enemy_responses=['对方中单可能先到。'], end_state='河口站不住。')
    second.update(enemy_responses=['守方可能后撤。'], end_state='仍有机会回中接线。',
                  abort_signals=['队友折返就收手。'])
    answer['recommendation'].update(preferred_option_id=second['id'], fallback_option_id=first['id'],
                                    switch_conditions=['队友折返就收手。', '看到另一人露头再评。'])
    check = validate_decision(answer, frame)
    assert check['status'] == 'PASS'
    card = render_decision(answer, check)
    assert second['enemy_responses'][0] in card and second['end_state'] in card
    assert first['enemy_responses'][0] not in card and first['end_state'] not in card
    assert card.count(second['abort_signals'][0]) == 1 and '看到另一人露头再评。' in card


def test_ranked_move_uses_players_own_path_evidence_if_available():
    frame, answer = player_case()
    frame['task']['round_comparison'] = {'lane': 'mid', 'target': 'dragon', 'help_seconds': 5}
    first, second = answer['options']
    first['id'], second['id'] = 'leave_now', 'help_then_leave'
    answer['options'].append(dict(deepcopy(second), id='clear_then_leave', action='先接兵线'))
    answer['recommendation'].update(preferred_option_id=first['id'], fallback_option_id=second['id'])
    for actor in ('self','ally'):
        frame['facts'][actor+'_path'] = dict(entity_id=actor,field='allied_path_start_sample',
                                             observed_at_seconds=9,value={'xz':[12,9]})
    frame['allied_path_fact_ids'] = ['self_path','ally_path']
    first['fact_refs'] = ['ally_path']
    assert validate_decision(answer, frame)['status'] == 'FAIL'
    first['fact_refs'].append('self_path')
    assert validate_decision(answer, frame)['status'] == 'PASS'
    first['fact_refs'] = ['ally_path']
    frame['allied_path_fact_ids'] = ['ally_path']
    assert validate_decision(answer, frame)['status'] == 'PASS'
