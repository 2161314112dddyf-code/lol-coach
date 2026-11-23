"""Team communication in the frozen player's answer, including quiet moments."""
from copy import deepcopy

import pytest

from lol_coach.decision_contract import TEAM_COORDINATION_REVIEW, output_schema, render_decision, validate_decision
from lol_coach.reasoning_frame import model_messages
from lol_coach.round_model_format import expand_round_response, prepare_round_request
from lol_coach.round_tools import ROUND_TOOLS
from test_personal_episode import pair
from test_round_model_format import data, record


def setup_coordination():
    bundle, answer = pair()
    frame = bundle['frame']
    frame['task']['team_coordination_review'] = TEAM_COORDINATION_REVIEW
    answer['team_coordination'] = dict(
        mode='communicate', recipient_id='ally', trigger='过河口前先提醒他。',
        known_information='我看到的只是队友最近的位置。', intended_action='从入口外侧掩护。',
        message='我在入口，等我一起走。', response_cue='我过河前看他是否向同一个入口靠。',
        fallback='队友仍在清兵就留在入口外。', fact_ids=[answer['facts_used'][0]['fact_id']])
    return bundle, answer


def ping(frame, answer, *, sender='0x1', sent=19, known_as='own_sent', kind='assist_me'):
    value = dict(kind=kind, observer_team_id=frame['decision']['observer_team_id'],
                 known_as=known_as, available_at_seconds=sent)
    frame['facts']['sent'] = dict(value=value, entity_id=sender, field='map_ping_sent',
                                  temporal_scope='communication_event', observed_at_seconds=sent)
    frame['recent_team_pings'] = dict(window_start_seconds=15, coverage='verified_events_only', fact_ids=['sent'])
    answer['facts_used'].append(dict(fact_id='sent', value=value))
    answer['team_coordination'].update(mode='already_signaled', message='', fact_ids=['sent'], ping_kind='assist_me')


def test_communicate_card_marks_message_as_a_proposal_and_names_the_ally():
    bundle, answer = setup_coordination()
    frame = bundle['frame']
    checked = validate_decision(answer, frame)
    assert checked['status'] == 'PASS', checked
    card = render_decision(answer, checked)
    assert '和 B 怎么配合' in card and '可以这样提醒' in card
    assert answer['team_coordination']['fallback'] in card
    assert answer['team_coordination']['response_cue'] in card


@pytest.mark.parametrize('changes', [
    dict(recipient_id='enemy'), dict(recipient_id='0x1'), dict(recipient_id='missing'),
    dict(message=''), dict(response_cue=' '), dict(fact_ids=['h_previous']), dict(fact_ids=[]),
    dict(mode='no_signal', message='', recipient_id='ally'),
    dict(mode='no_signal', recipient_id=None, message='已经有人回应'),
])
def test_rejects_wrong_recipient_unsupported_facts_and_contradictory_mode(changes):
    bundle, answer = setup_coordination()
    answer['team_coordination'].update(changes)
    assert validate_decision(answer, bundle['frame'])['status'] == 'FAIL'


@pytest.mark.parametrize('overrides', [
    dict(), dict(sender='ally', known_as='delivered_to_team'), dict(sent=10), dict(sent=21), dict(kind='retreat')
])
def test_already_signaled_requires_matching_own_send_in_current_window(overrides):
    bundle, answer = setup_coordination()
    ping(bundle['frame'], answer, **overrides)
    check = validate_decision(answer, bundle['frame'])
    assert check['status'] == ('FAIL' if overrides else 'PASS'), check
    if not overrides:
        card = render_decision(answer, check)
        assert '已发过的信号' in card and '可以这样提醒' not in card


def test_can_withhold_a_ping_with_reason_or_render_old_card():
    bundle, answer = setup_coordination()
    frame = bundle['frame']
    answer['team_coordination'].update(mode='no_signal', recipient_id=None, message='', response_cue='')
    checked = validate_decision(answer, frame)
    assert checked['status'] == 'PASS'
    assert '这时可以不发信号' in render_decision(answer, checked)
    answer.pop('team_coordination')
    assert validate_decision(answer, frame)['status'] == 'FAIL'
    frame['task'].pop('team_coordination_review')
    checked = validate_decision(answer, frame)
    assert checked['status'] == 'PASS'
    assert '这时可以不发信号' not in render_decision(answer, checked)


def test_ollama_requires_plan_tool_and_constrains_recipient_and_prior_ping():
    bundle, answer = setup_coordination()
    frame = bundle['frame']
    schema = output_schema(frame)
    request = dict(messages=model_messages(bundle, schema), tools=ROUND_TOOLS, response_schema=schema)
    record(request, 'review_personal_action')
    with pytest.raises(ValueError, match='required_round_tools_missing'):
        prepare_round_request(request, remaining_calls=1)
    record(request, 'review_round_plan', 'q2')
    _, wire = prepare_round_request(request, remaining_calls=1)
    variants = wire['properties']['answer']['properties']['team_coordination']['anyOf']
    permitted = {v['properties']['mode']['enum'][0]: v['properties']['recipient_id']['enum'] for v in variants}
    assert permitted == {'communicate': ['ally'], 'no_signal': [None]}
    assert expand_round_response(request, data(answer)) == dict(answer=answer)


def test_quiet_personal_frame_can_focus_on_player_without_comms_or_plan_call():
    bundle, answer = pair()
    frame = bundle['frame']
    frame['task']['team_coordination_trigger'] = {'active': False}
    frame['task']['macro_round_review'] = 'macro-round/v1'
    schema = output_schema(frame)
    request = dict(messages=model_messages(bundle, schema), tools=ROUND_TOOLS, response_schema=schema)
    record(request, 'review_personal_action')
    _, wire = prepare_round_request(request, remaining_calls=1)
    schema_role = wire['properties']['answer']['properties']['role_assignments']
    assert schema_role['required'] == ['player'] and 'others' in schema_role['properties']
    assert 'team_coordination' not in wire['properties']['answer']['properties']
    quiet_answer = deepcopy(answer)
    quiet_answer['macro_round'] = dict(
        transition='start', intent='develop', map_goal='先吃这一波兵。',
        enabling_condition='对手暂时没有让你离线的动作。', opponent_reply='对手可能抢补刀位置。',
        fact_refs=['gold'], change_refs=[])
    quiet_answer['role_assignments'] = quiet_answer['role_assignments'][:1]
    assert expand_round_response(request, data(quiet_answer)) == {'answer': quiet_answer}
    checked = validate_decision(quiet_answer, frame)
    assert checked['status'] == 'PASS'
    player_card = render_decision(quiet_answer, checked)
    assert '## 地图计划' not in player_card and '你现在的第一步' in player_card
