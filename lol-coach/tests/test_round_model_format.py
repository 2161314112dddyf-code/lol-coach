"""Wire-format constraints and semantic round trips; no model verdict fixture."""
from copy import deepcopy
import json

import pytest

from lol_coach.decision_contract import TIME_FIELDS, output_schema, validate_decision
from lol_coach.reasoning_frame import canonical, model_messages
from lol_coach.round_chain import attach_previous_plan
from lol_coach.round_model_format import prepare_round_request, expand_round_response
from lol_coach.round_tools import ROUND_TOOLS, bind_round
from test_round_agent_integration import round_answer
from test_round_chain import answer_for, bundle_at


def setup(*, prior=False):
    b = bundle_at(20)
    if prior:
        old = bundle_at(10)
        b = attach_previous_plan(b, old, answer_for(old))
    b = bind_round(b, 'mid', 'dragon', 5)
    schema = output_schema()
    return b, dict(messages=model_messages(b, schema), tools=ROUND_TOOLS, response_schema=schema)


def record(req, name, q='q1', **arguments):
    req['messages'].append({'role':'assistant', 'content':canonical({'tool_requests':[
        dict(id=q,name=name,arguments=arguments)]})})
    req['messages'].append({'role':'user','content':canonical({'tool_results':[{'id':q,'name':name}]})})


def data(answer):
    a = deepcopy(answer)
    a['facts_used'] = [x['fact_id'] for x in a['facts_used']]
    a['role_assignments'] = dict(zip(('player','ally','enemy'),a['role_assignments']))
    options = {}
    for row in a['options']:
        options[row.pop('id')] = row
        ids = row.pop('time_budget')['calculation_refs']
        row['calculation_id'] = ids[0] if ids else None
    a['options'] = options
    return {'answer':a}


def test_first_query_bound_to_advertised_tools_and_ids():
    _, req = setup()
    before = deepcopy(req)
    messages, only_tools = prepare_round_request(req)
    assert req == before and 'answer' not in only_tools['properties']
    items = only_tools['properties']['tool_requests']['items']['anyOf']
    calls = {i['properties']['name']['enum'][0]:i['properties'] for i in items}
    assert 'compare_round_options' in calls and 'read_history' not in calls
    assert calls['get_reference']['arguments']['properties']['reference_id']['enum'] == ['rule1']
    assert json.loads(messages[1]['content'])['decision_frame'] == json.loads(req['messages'][1]['content'])['decision_frame']
    assert 'output_schema' not in json.loads(messages[1]['content'])


@pytest.mark.parametrize('linked',[True,False])
def test_legal_envelope_roundtrips_and_preserves_every_decision_field(linked):
    bundle, req = setup(prior=linked)
    record(req,'compare_round_options')
    if linked:
        _, spec = prepare_round_request(req)
        assert 'answer' not in spec['properties']
        record(req,'review_round_plan','q2')
    _, spec = prepare_round_request(req)
    answer_spec = spec['anyOf'][0]['properties']['answer']
    assert ('continuation' in answer_spec['required']) == linked
    assert sorted(answer_spec['properties']['options']['required']) == ['clear_then_leave','help_then_leave','leave_now']
    result = round_answer(bundle)
    wire = data(result)
    original = deepcopy((req,wire))
    restored = expand_round_response(req,wire)
    assert restored == {'answer':result} and original == (req,wire)
    assert validate_decision(restored['answer'],bundle['frame'])['status'] == 'PASS'


def test_preserves_partial_registered_budget_only_for_its_own_action():
    bundle, req = setup()
    a = round_answer(bundle)
    payload = json.loads(req['messages'][1]['content'])
    payload['decision_frame']['calculations']['calc_fixture'] = dict(option_id='help_then_leave',
                                                                    time_budget={'travel_seconds':[1,2]})
    req['messages'][1]['content'] = canonical(payload)
    wire = data(a)
    wire['answer']['options']['help_then_leave']['calculation_id'] = 'calc_fixture'
    expanded = expand_round_response(req,wire)['answer']
    budget = expanded['options'][1]['time_budget']
    assert budget['travel_seconds'] == [1,2] and budget['calculation_refs'] == ['calc_fixture']
    assert all(budget[k] is None for k in TIME_FIELDS if k != 'travel_seconds')
    wire['answer']['options']['leave_now']['calculation_id'] = 'calc_fixture'
    with pytest.raises(ValueError, match='invalid_selected_calculation'):
        expand_round_response(req,wire)


@pytest.mark.parametrize('override', [['made-up'],['h_gold'],['gold','made-up','gold'],[{'fact_id':'gold','value':777}]])
def test_rejects_invented_history_or_rewritten_facts(override):
    b, req = setup()
    wire = data(round_answer(b))
    wire['answer']['facts_used'] = override
    with pytest.raises(ValueError, match='invalid_selected_fact_ids'):
        expand_round_response(req,wire)


def test_selected_known_fact_repeats_expand_once_in_first_appearance_order():
    b, req = setup()
    wire = data(round_answer(b))
    wire['answer']['facts_used'] = ['ally_hp','gold','ally_hp','gold']
    assert [x['fact_id'] for x in expand_round_response(req,wire)['answer']['facts_used']] == ['ally_hp','gold']


def test_legacy_tools_allow_answer_on_every_call_and_never_require_missing_round_tools():
    _, req = setup(prior=True)
    req['tools'] = [t for t in req['tools'] if t['function']['name']=='get_reference']
    for remaining in (2,1):
        _, spec = prepare_round_request(req,remaining_calls=remaining)
        branch = spec.get('anyOf',[spec])[0]
        fields = branch['properties']['answer']['properties']
        recs = [v['properties'] for v in fields['recommendation']['anyOf']]
        assert all('supported' not in v['confidence']['enum'] for v in recs)
        assert {v['preferred_option_id']['enum'][0] for v in recs} == {'leave_now','help_then_leave','clear_then_leave',None}
        for rec in recs:
            preferred, = rec['preferred_option_id']['enum']
            if preferred is not None:
                assert preferred not in rec['fallback_option_id']['enum'] and None not in rec['fallback_option_id']['enum']
        variants = {v['properties']['status']['enum'][0]:v['properties']
                    for v in fields['options']['properties']['leave_now']['anyOf']}
        assert variants['conditional']['preconditions']['minItems'] == 1
        assert all(variants['supported'][k]['maxItems']==0 for k in ('assumptions','preconditions','ally_requirements'))


def test_tools_are_not_reissued_or_given_stale_call_ids():
    _, req = setup()
    record(req,'get_reference',reference_id='rule1')
    _, spec = prepare_round_request(req)
    items = spec['properties']['tool_requests']['items']['anyOf']
    names = [row['properties']['name']['enum'][0] for row in items]
    assert 'get_reference' not in names
    assert all(row['properties']['id']['enum']==['q2'] for row in items)


def test_model_can_probe_another_wait_in_the_same_frame():
    _, req = setup()
    record(req,'compare_help_duration',help_seconds=9)
    _, spec = prepare_round_request(req)
    choices = spec['properties']['tool_requests']['items']['anyOf']
    tool, = [row['properties'] for row in choices if row['properties']['name']['enum']==['compare_help_duration']]
    assert tool['arguments']['properties']=={'help_seconds':{'type':'number','minimum':0}}
    assert tool['id']['enum']==['q2']


def test_last_query_slot_batches_both_outstanding_tools_for_a_linked_frame():
    _, req = setup(prior=True)
    record(req,'get_reference','q2',reference_id='rule1')
    _, fmt = prepare_round_request(req,remaining_calls=2)
    spec = fmt['properties']['tool_requests']
    assert spec['minItems'] == spec['maxItems'] == 2 and spec['items'] is False
    two = [p['properties'] for p in spec['prefixItems']]
    assert [p['name']['enum'][0] for p in two] == ['compare_round_options','review_round_plan']
    assert [p['id']['enum'][0] for p in two] == ['q1','q3']
    assert all(p['arguments']['additionalProperties'] is False for p in two)


def test_last_query_slot_queries_only_one_missing_tool():
    _, req = setup(prior=True)
    record(req,'review_round_plan')
    _, fmt = prepare_round_request(req,remaining_calls=2)
    spec = fmt['properties']['tool_requests']
    assert spec['minItems'] == spec['maxItems'] == 1
    assert spec['items']['properties']['name']['enum']==['compare_round_options']


def test_final_slot_only_returns_an_answer_or_explains_missing_reads():
    _, req = setup()
    with pytest.raises(ValueError, match='required_round_tools_missing_at_final_call'):
        prepare_round_request(req,remaining_calls=1)
    record(req,'compare_round_options')
    messages, fmt = prepare_round_request(req,remaining_calls=1)
    assert list(fmt['properties'])==['answer']
    assert '可调用工具' not in messages[-1]['content'] and '玩家现在要做的第一步' in messages[-1]['content']
    with pytest.raises(ValueError, match='invalid_remaining_model_calls'):
        prepare_round_request(req,remaining_calls=0)
