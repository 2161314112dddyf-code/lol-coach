"""Synthetic boundary regressions for the shared runner, plan and MCP tools."""
from copy import deepcopy
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

import pytest

from lol_coach.decision_contract import validate_decision
from lol_coach.reasoning_frame import compile_frame
from lol_coach.reasoning_runner import run_reasoning
from lol_coach.round_chain import attach_previous_plan
from lol_coach.round_tools import bind_round, history_catalog, round_call
from test_macro_snapshot import bundles, query
from test_round_chain import answer_for, bundle_at
from test_round_options import clock
from test_round_plan import add_fact


def round_answer(bundle):
    allowed = deepcopy(bundle)
    allowed['frame']['task'].pop('round_comparison')
    result = answer_for(allowed)
    first, second = result['options']
    first['id'], second['id'] = 'leave_now', 'help_then_leave'
    result['options'].append(dict(deepcopy(second), id='clear_then_leave'))
    result['options'][-1]['action'] = 'Clear the wave before joining.'
    result['recommendation'].update(preferred_option_id=first['id'], fallback_option_id=second['id'])
    return result


def test_discovered_tools_are_used_before_card_and_do_not_mutate_locked_data():
    bundle = bind_round(bundle_at(8), 'mid', 'dragon', 5)
    original = deepcopy(bundle)
    card = round_answer(bundle)
    calls = iter([{'answer':card}, {'tool_requests':[dict(id='q1', name='compare_round_options', arguments={})]},
                  {'answer':card}])
    result = run_reasoning(bundle, lambda _:next(calls), round_tool_call=lambda n,a:round_call(bundle,n,a))
    assert result['status'] == 'completed' and result['model_calls'] == 3
    assert result['trace'][2]['result']['status'] == 'FAIL'
    assert bundle == original
    outs = next(e['results'] for e in result['trace'] if e['event']=='tool_results')
    assert outs[0]['content']['options'][1]['depart_at'] == [13,13]
    with pytest.raises(ValueError):
        round_call(bundle, 'compare_round_options', {'help_seconds': 20})


def test_queried_range_cannot_move_from_the_immediate_route_to_the_delayed_option(bundles):
    base = compile_frame(query(bundles, at=8, player='self'))
    clock(base['frame'], 'immediate_route_duration', [1,2])
    bound = bind_round(base, 'mid', 'dragon', 5)
    calc, = bound['frame']['calculations'].values()
    assert calc['option_id']=='leave_now' and calc['time_budget']['travel_seconds']==[1,2]


def test_agent_can_vary_wait_without_rebinding_card_or_borrowing_another_plans_benefit():
    base = bundle_at(8)
    clock(base['frame'], 'target_deadline', [14,15])
    clock(base['frame'], 'target_finish_with_help', [16,17], help_seconds=5)
    clock(base['frame'], 'target_finish_without_help', [18,19], help_seconds=5)
    bound = bind_round(base, 'mid', 'dragon', 5)
    before = deepcopy(bound)
    result = round_call(bound, 'compare_help_duration', {'help_seconds':9})
    assert result['at_seconds']==8 and result['default_help_seconds']==5
    assert result['option']['depart_at']==[17,17] and result['option']['target_window']=='too_late'
    assert result['option']['arrive_at'] is None and result['additional_objective_contribution'] is None
    default = round_call(bound, 'compare_round_options', {})
    assert default['options'][1]['depart_at']==[13,13] and default['additional_objective_contribution'] is not None
    assert bound==before
    for args in ({'help_seconds':4,'at_seconds':10}, {'help_seconds':True}, {'help_seconds':-1}):
        with pytest.raises(ValueError):
            round_call(bound, 'compare_help_duration', args)


def test_invalid_wait_in_model_batch_prevents_all_lookups():
    bound = bind_round(bundle_at(8), 'mid', 'dragon', 5)
    requests = [dict(name='compare_round_options', id='q1', arguments={}),
                dict(name='compare_help_duration', id='q2', arguments={'help_seconds':'9'})]
    calls = []
    result = run_reasoning(bound, lambda _: {'tool_requests':requests}, round_tool_call=lambda n,a:calls.append(n))
    assert calls==[] and result['status']=='failed' and 'help_seconds' in result['error']


def test_cross_option_numeric_citation_fails_even_when_the_seconds_match():
    base = bundle_at(8)
    clock(base['frame'], 'immediate_route_duration', [1,2])
    bound = bind_round(base, 'mid', 'dragon', 5)
    card = round_answer(bound)
    cid, = bound['frame']['calculations']
    card['options'][0]['time_budget'].update(travel_seconds=[1,2], calculation_refs=[cid])
    assert validate_decision(card,bound['frame'])['status']=='PASS'
    card['options'][1]['time_budget'].update(travel_seconds=[1,2], calculation_refs=[cid])
    assert validate_decision(card,bound['frame'])['status']=='FAIL'


def test_machine_placeholders_do_not_become_a_published_player_card():
    bound = bind_round(bundle_at(8), 'mid', 'dragon', 5)
    card = round_answer(bound)
    card['recommendation']['why'] = 'no_valid_action_id_found'
    card['options'][0]['costs'] = ['%_time_budgets%_used%', '], ']
    result = validate_decision(card, bound['frame'])
    assert result['status']=='FAIL'
    assert {e['path'] for e in result['errors']} == {'$.recommendation.why','$.options[0].costs'}


def test_distinct_option_numbers_and_unitless_cost_are_still_placeholders():
    bound = bind_round(bundle_at(8), 'mid', 'dragon', 5)
    card = round_answer(bound)
    for option, label in zip(card['options'], ('走法1','方案乙','Option #3')):
        option.update(action=label, costs=['0'])
    result = validate_decision(card, bound['frame'])
    assert result['status']=='FAIL'
    assert {e['path'] for e in result['errors']} == {
        f'$.options[{i}].{field}' for i in range(3) for field in ('action','costs')}


def test_observed_objective_kill_reopens_only_options_which_relied_on_that_target():
    old, new = bundle_at(10), bundle_at(20)
    pit = add_fact(old,'dragon','dragon_pit_observation','alive in view',9,'observed_sample')
    kill = add_fact(new,'dragon','allied_dragon_kill',{'name_from_announcement':'Cloud Drake'},18,'public_event')
    prev = answer_for(old)
    assert round_call(attach_previous_plan(new,old,prev),'review_round_plan',{})['status']=='monitor'
    prev['options'][0]['fact_refs'].append(pit)
    linked = attach_previous_plan(new,old,prev)
    report = round_call(linked,'review_round_plan',{})
    assert report['status']=='reopen'
    signal, = report['triggers']
    assert (signal['kind'],signal['current_fact_id'],signal['option_ids'])==('objective_secured',kill,['a'])
    catalog = history_catalog(linked['frame'])
    hid = next(iter(catalog['task']['previous_plan']['historical_facts']))
    assert 'value' not in catalog['task']['previous_plan']['historical_facts'][hid]
    assert 'value' in round_call(linked,'read_history',{'history_id':hid})['historical_fact']
    with pytest.raises(ValueError):
        round_call(linked,'read_history',{'history_id':kill})


def test_round_cli_from_frozen_bundle_to_three_real_mcp_calls(bundles, tmp_path):
    interpreter = os.environ.get('REVIEW_MCP_PYTHON')
    if not interpreter and find_spec('mcp') is None:
        pytest.skip('optional review-mcp dependency is absent')
    root = Path(__file__).resolve().parents[1]
    sessions = root/'data/private/reasoning_sessions'
    sessions.mkdir(parents=True, exist_ok=True)
    bundle = compile_frame(query(bundles, at=8, player='self'))
    bundle['audit']['source_replay_sha256'] = 'a'*64
    path = tmp_path/'source.json'
    path.write_text(json.dumps(bundle),encoding='utf-8')
    with TemporaryDirectory(dir=sessions) as parent:
        out = Path(parent)/'result'
        proc = subprocess.run([interpreter or sys.executable,'-m','scripts.run_review_agent',
            '--bundle',str(path),'--lane','mid','--target','dragon','--help-seconds','5',
            '--backend','probe','--output',str(out)],cwd=root,capture_output=True,timeout=50)
        assert proc.returncode == 0, proc.stderr.decode(errors='replace')
        step, = json.loads((out/'manifest.json').read_bytes())['steps']
        assert step['direct_equals_mcp'] and step['rejected_overrides']==2
        evidence = json.loads((out/'01/evidence.json').read_bytes())
        assert evidence['compare_round_options']['options'][1]['depart_at']==[13,13]
        assert evidence['review_round_plan']['status']=='no_previous_plan'
        assert 'opponents' in evidence['enemy_sightings']
