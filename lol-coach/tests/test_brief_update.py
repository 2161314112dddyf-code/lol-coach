"""A short update still needs a frozen source, a decision and a signed review."""
from copy import deepcopy
import json

import pytest

from lol_coach.brief_update import SCHEMA, bind_brief, brief_context
from lol_coach.decision_contract import output_schema, render_decision, validate_decision
from lol_coach.personal_episode import bind_personal_actions, refresh_identity
from lol_coach.reasoning_frame import digest
from lol_coach.reasoning_runner import run_reasoning
from lol_coach.round_chain import attach_previous_plan
from lol_coach.round_model_format import prepare_round_request, expand_round_response
from lol_coach.round_tools import round_call
from test_personal_episode import base, pair


def contact_bundle(at=20, when=None):
    b = bind_personal_actions(base(at))
    when = at if when is None else when
    src = dict(offset=123)
    receipt = dict(offset=111)
    actor = 'entity:enemy'
    pos = dict(xz=[200, 100], sampled_at=when)
    b['frame']['facts']['sighting'] = dict(entity_id=actor, field='observer_visibility',
        value=dict(visible=True, last_observed_position=pos), temporal_scope='queried_at_decision_time',
        observed_at_seconds=at)
    b['audit'].setdefault('fact_sources', {})['sighting'] = dict(evidence=[
        dict(mode='visible_path_start', time_seconds=at, source=src, visibility_record=receipt)])
    sample = dict(subject=actor, team_id=b['frame']['decision']['observer_team_id'],
                  time_seconds=at, xz=pos['xz'], source=src, visibility_record=receipt)
    selected = dict(triggers=[dict(kind='nearby_enemy_became_visible', subject=actor, at=at, enemy_sample=sample)])
    return refresh_identity(b), selected


def answer(frame):
    return dict(schema=SCHEMA, frame_id=frame['frame_id'], change=brief_context(frame)['verified_contact_observation'],
                disposition='retain' if frame['task'].get('previous_plan') else 'unanchored',
                immediate_action='沿能退回的路等队友靠近。', switch_if='有人封住出口就先退。',
                fact_refs=['sighting'])


def test_file_packet_direct_mcp_and_local_wire_agree_without_a_full_answer():
    original, selected = contact_bundle()
    b = bind_brief(original, selected)
    f = b['frame']
    model_requests = []
    def generate(request):
        model_requests.append(request)
        return {'answer': answer(f)}
    out = run_reasoning(b, generate, round_tool_call=lambda n, args: round_call(b, n, args),
                        answer_review=lambda result: dict(accepted=True, issues=[]))
    assert out['status'] == 'completed' and out['model_calls'] == 1
    assert out['trace'][0]['origin'] == 'host_prefetch'
    request, = model_requests
    assert not request['tools']
    packet = json.loads(request['messages'][1]['content'])
    assert packet == brief_context(f) and packet['trigger_fact_ids'] == ['sighting']
    assert 'references' not in packet and 'options' not in request['response_schema']['properties']
    wire, grammar = prepare_round_request(request)
    local_packet = json.loads(wire[1]['content'])
    label, = local_packet['trigger_fact_ids']
    assert local_packet['facts'][label] == packet['facts']['sighting']
    assert len(grammar['required']) == 4
    a = answer(f)
    local = dict(本人第一步=a['immediate_action'], 何时换手=a['switch_if'],
                 计划关系=a['disposition'], 证据编号=[label])
    assert expand_round_response(request, local) == {'answer': a}
    assert a['change'] in render_decision(a, out['validation'])
    assert 'options' in output_schema(original['frame'])['properties']
    failed = run_reasoning(b, generate, round_tool_call=lambda n, args: {})
    assert failed['status'] == 'failed' and failed['model_calls'] == 0


def test_only_bound_triggers_and_current_sample_times_can_be_used():
    b, selection = contact_bundle()
    assert brief_context(bind_brief(b)['frame'])['trigger_fact_ids'] == []
    wrong = deepcopy(selection)
    wrong['triggers'][0]['enemy_sample']['source'] = {'offset': 444}
    with pytest.raises(ValueError, match='contact_evidence_mismatch'):
        bind_brief(b, wrong)
    f = bind_brief(b, selection)['frame']
    for update in [dict(fact_refs=['not_in_packet']), dict(fact_refs=['sighting']*2),
                   dict(disposition='retain'), dict(frame_id='other'), dict(immediate_action='switch_if'),
                   dict(immediate_action='观察到 E3 就在这里等。'),
                   dict(switch_if='有上次建议才判断延续或改选。'),
                   dict(immediate_action=answer(f)['change'])]:
        assert validate_decision(dict(answer(f), **update), f)['status'] == 'FAIL'
    future, _ = contact_bundle(when=21)
    with pytest.raises(ValueError, match='position_time'):
        brief_context(bind_brief(future)['frame'])


def test_full_short_full_retains_the_actual_prior_decision_and_evidence():
    first, old_answer = pair()
    b, selected = contact_bundle(25)
    middle = attach_previous_plan(bind_brief(b, selected), first, old_answer)
    f = middle['frame']
    assert brief_context(f)['previous_plan']['first_step'] == old_answer['immediate_action']
    a = answer(f)
    third = attach_previous_plan(base(30), middle, a)['frame']['task']['previous_plan']
    assert third['previous_answer_sha256'] == digest(a)
    assert third['decision_card']['immediate_action'] == a['immediate_action']
    assert third['historical_facts']['h_sighting']['original_fact_id'] == 'sighting'
