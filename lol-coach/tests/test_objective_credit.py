from copy import deepcopy

from lol_coach.decision_contract import output_schema, render_decision, validate_decision
from lol_coach.reasoning_frame import model_messages
from lol_coach.round_chain import attach_previous_plan
from lol_coach.round_model_format import prepare_round_request
from lol_coach.round_tools import ROUND_TOOLS, round_call
from test_macro_round_contract import bound, card
from test_round_chain import freeze
from test_round_model_format import record


def event(field='allied_dragon_kill', **extra):
    return dict(entity_id='self', field=field, observed_at_seconds=18, available_at_seconds=19,
                temporal_scope='public_event', value=dict(name_from_announcement='Cloud Drake', **extra))


def test_team_announcement_attached_to_player_cannot_grant_a_personal_kill():
    before = bound(10)
    before['frame']['facts']['pit'] = dict(entity_id='dragon-pit', field='dragon_pit_observation',
        value={'alive': True}, observed_at_seconds=9, temporal_scope='player_view_at_video_frame')
    freeze(before)
    prior = card(before)
    prior['options'][0]['fact_refs'].append('pit')
    new = bound(20)
    new['frame']['facts']['team_news'] = event()
    linked = attach_previous_plan(freeze(new), before, prior)
    plan = round_call(linked, 'review_round_plan', {})
    assert plan['objective_kill_events']['team_news']['killer_entity_id'] is None
    assert plan['objective_kill_events']['team_news']['credited_team_id'] == 100
    trigger, = (r for r in plan['triggers'] if r['kind'] == 'objective_secured')
    assert trigger['entity_id'] == 'dragon' and trigger['current_fact_id'] == 'team_news'
    answer = card(linked, 'continue')
    answer['facts_used'].append({'fact_id': 'team_news', 'value': event()['value']})
    claim = {'fact_id': 'team_news', 'killer_entity_id': None}
    answer['objective_kill_claims'] = [claim]
    assert validate_decision(answer, linked['frame'])['status'] == 'PASS'
    claim['killer_entity_id'] = 'self'
    result = validate_decision(answer, linked['frame'])
    assert [e['path'] for e in result['errors']] == ['$.objective_kill_claims[0].killer_entity_id']


def test_only_a_contemporaneous_named_feed_can_credit_a_rostered_killer():
    b = bound(20)
    frame = b['frame']
    named = event('public_objective_kill_feed', objective_kind='dragon', killer_entity_id='enemy', killer_team_id=200)
    frame['facts']['signed'] = named
    wrong_team = deepcopy(named)
    wrong_team['value']['killer_team_id'] = 100
    frame['facts'].update(wrong_team=wrong_team, endgame=dict(named, temporal_scope='final_metadata_only'),
                          pit=dict(named, field='dragon_pit_observation'))
    freeze(b)
    events = round_call(b, 'review_round_plan', {})['objective_kill_events']
    assert list(events) == ['signed']
    assert events['signed']['killer_entity_id'] == 'enemy' and events['signed']['credited_team_id'] == 200
    answer = card(b)
    for fid in ('signed', 'endgame', 'pit', 'wrong_team'):
        answer['facts_used'].append(dict(fact_id=fid, value=frame['facts'][fid]['value']))
    claim = dict(fact_id='signed', killer_entity_id='enemy')
    answer['objective_kill_claims'] = [claim]
    assert validate_decision(answer, frame)['status'] == 'PASS'
    for fid, actor in [('signed', 'self'), ('pit', 'enemy'), ('endgame', 'enemy'), ('wrong_team', 'enemy')]:
        claim.update(fact_id=fid, killer_entity_id=actor)
        assert validate_decision(answer, frame)['status'] == 'FAIL'
    frame['facts']['signed']['available_at_seconds'] = 21
    claim.update(fact_id='signed', killer_entity_id='enemy')
    assert validate_decision(answer, frame)['status'] == 'FAIL'


def test_cited_event_requires_credit_in_new_session_and_displays_only_verified_attribution():
    b = bound(20)
    frame = b['frame']
    frame['task']['require_objective_credit'] = True
    hud = dict(entity_id='dragon-pit', field='dragon_pit_observation',
               value='玩家画面出现“我方队伍已经击杀了云霄亚龙！”公告。',
               temporal_scope='player_view_at_video_frame', observed_at_seconds=18)
    signed = event('public_objective_kill_feed', objective_kind='dragon', killer_entity_id='enemy', killer_team_id=200)
    signed['value']['name_from_announcement'] = 'Infernal Drake'
    frame['facts'].update(team_hud=hud, signed=signed)
    freeze(b)
    answer = card(b)
    for fid in ('team_hud', 'signed'):
        answer['facts_used'].append(dict(fact_id=fid, value=frame['facts'][fid]['value']))
    legacy = deepcopy(frame)
    legacy['task'].pop('require_objective_credit')
    assert validate_decision(answer, legacy)['status'] == 'PASS'
    assert validate_decision(answer, frame)['errors'][0]['path'] == '$.objective_kill_claims'
    answer['objective_kill_claims'] = [dict(fact_id='team_hud', killer_entity_id=None)]
    assert validate_decision(answer, frame)['status'] == 'FAIL'
    answer['objective_kill_claims'].append(dict(fact_id='signed', killer_entity_id='enemy'))
    valid = validate_decision(answer, frame)
    assert valid['status'] == 'PASS'
    player_card = render_decision(answer, valid)
    assert '云霄亚龙由蓝方击杀。这条公告能确认队伍，个人击杀者未知。' in player_card
    assert '炼狱亚龙的击杀记在红方 C 名下。' in player_card

    schema = output_schema(frame)
    req = dict(messages=model_messages(b, schema), tools=ROUND_TOOLS, response_schema=schema)
    record(req, 'compare_round_options')
    record(req, 'review_round_plan', 'q2')
    _, wire = prepare_round_request(req, remaining_calls=1)
    choices = wire['properties']['answer']['properties']['objective_kill_claims']['items']['anyOf']
    assert {row['properties']['fact_id']['enum'][0]: row['properties']['killer_entity_id']['enum']
            for row in choices} == {'team_hud': [None], 'signed': ['enemy']}
