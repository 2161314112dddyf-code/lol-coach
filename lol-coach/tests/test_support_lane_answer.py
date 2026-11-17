"""Synthetic support decisions, grounded references and local wire compatibility."""
from copy import deepcopy

import pytest

from lol_coach.decision_contract import SUPPORT_LANE_REVIEW, output_schema, render_decision, validate_decision
from lol_coach.reasoning_frame import model_messages
from lol_coach.round_model_format import expand_round_response, prepare_round_request
from lol_coach.round_tools import ROUND_TOOLS, bind_round
from test_round_agent_integration import round_answer
from test_round_chain import bundle_at, freeze
from test_round_model_format import data, record
from test_round_options import add_fact


@pytest.fixture
def scenario():
    bundle = bundle_at(20)
    frame = bundle['frame']
    frame['lineup'].append(dict(entity_id='guard', champion='D', relation='enemy',
                                current_fact_ids=[], history_fact_ids=[]))
    fid = add_fact(frame, 'lane_fact_ids', entity='lane:bot', field='lane_current_units_and_groups',
                   value=dict(lane='bot', count_scope='own_team_observed_live_only',
                              counts=[dict(team_id=100, kind='melee', count=2)]),
                   unit=None, scope='queried_at_decision_time', when=20)
    base = bind_round(freeze(bundle), 'bot', 'dragon', 5)
    answer = round_answer(base)
    actors = dict(support='self', carry='ally', enemy_carry='enemy', enemy_support='guard')
    bundle = bind_round(base, 'bot', 'dragon', 5, bottom_lane_actors=actors)
    frame = bundle['frame']
    answer['frame_id'] = frame['frame_id']
    answer['role_assignments'].append(dict(actor_id='guard', role='挡住进路', fact_refs=[], assumptions=[]))
    answer['facts_used'].append(dict(fact_id=fid, value=frame['facts'][fid]['value']))
    option = answer['options'][2]
    option.update(action='送兵进塔后去河道入口接打野', gains=['打野少探一个草'],
                  costs=['搭档被对手推开可能漏经验'], abort_signals=['搭档被迫向前就放弃'])
    answer['lane_plan'] = dict(pressure='站在能掩护搭档和威胁补刀的位置', if_open='对方孤立补刀且搭档能跟时打一轮',
        if_denied='对手拉远就留控制看住对面辅助', fact_refs=['gold', fid],
        roam=dict(option_id=option['id'], wave_number=None, wave_condition='确认这批兵进塔再离开',
                  short_play='搭档能独自接线才探河道入口，有人前压就回头',
                  committed_play='中单留得住目标才进中路，两人已退就取消',
                  return_by='下一批兵需要搭档冒险接之前折返'))
    return bundle, answer, fid


def test_card_renders_both_reactions_and_reuses_selected_roams_costs(scenario):
    bundle, answer, _ = scenario
    result = validate_decision(answer, bundle['frame'])
    assert result['status'] == 'PASS', result['errors']
    card = render_decision(answer, result)
    plan, option = answer['lane_plan'], answer['options'][2]
    for value in (plan['pressure'], plan['if_open'], plan['if_denied'], plan['roam']['return_by'],
                  plan['roam']['wave_condition'], plan['roam']['short_play'], plan['roam']['committed_play'],
                  option['gains'][0], option['costs'][0], option['abort_signals'][0], answer['open_questions'][0]):
        assert value in card
    assert '等条件满足再走' in card


@pytest.mark.parametrize('change', [
    lambda a, f: a['lane_plan'].update(if_denied=a['lane_plan']['if_open']),
    lambda a, f: a['lane_plan']['roam'].update(committed_play=a['lane_plan']['roam']['short_play']),
    lambda a, f: a['lane_plan']['roam'].update(option_id='other_trip'),
    lambda a, f: a['lane_plan']['roam'].update(wave_number=4),
    lambda a, f: a['lane_plan']['roam'].update(wave_condition='第四波直接离线'),
    lambda a, f: a['options'][2].update(gains=[]),
    lambda a, f: a['options'][2].update(status='supported', preconditions=[], ally_requirements=[]),
    lambda a, f: a['lane_plan'].update(fact_refs=['gold']),
    lambda a, f: a['lane_plan'].update(fact_refs=[f]),
    lambda a, f: a['facts_used'].pop(),
    lambda a, f: a['role_assignments'].pop(),
    lambda a, f: a.update(open_questions=[]),
])
def test_rejects_unsupported_or_incomplete_lane_claims(scenario, change):
    bundle, answer, fid = scenario
    change(answer, fid)
    assert validate_decision(answer, bundle['frame'])['status'] == 'FAIL'


def test_only_tagged_frames_request_and_require_the_lane_plan(scenario):
    bundle, answer, _ = scenario
    del answer['lane_plan']
    assert validate_decision(answer, bundle['frame'])['status'] == 'FAIL'
    old = deepcopy(bundle)
    assert old['frame']['task'].pop('bottom_lane_review') == SUPPORT_LANE_REVIEW
    schema = output_schema(old['frame'])
    assert 'lane_plan' not in schema['properties']
    assert 'support_lane_opportunity' not in model_messages(old, schema)[0]['content']
    assert validate_decision(answer, old['frame'])['status'] == 'PASS'


def test_destination_choice_is_scoped_and_cites_both_teammates(scenario):
    old, answer, _ = scenario
    frame = old['frame']
    roles = {'ally_mid':'m', 'ally_jungle':'j'}
    refs = []
    for role, actor in roles.items():
        frame['lineup'].append(dict(entity_id=actor, champion=actor, relation='ally',
                                    current_fact_ids=[], history_fact_ids=[]))
        refs.append(add_fact(frame, 'allied_path_fact_ids', entity=actor, field='allied_path_start_sample',
                             value=dict(observer_team_id=100, xz=[1, 2]), unit='map11_world_xz',
                             scope='historical_path_start_sample', when=19))
    bundle = bind_round(freeze(old), 'bot', 'dragon', 5, roam_actors=roles)
    frame = bundle['frame']
    answer.update(frame_id=frame['frame_id'])
    assert validate_decision(answer, frame)['status'] == 'FAIL'
    choice = dict(preferred='hold_bot', alternative='mid_lane', why='打野暂时无需接应，中路对手已退，先陪搭档接线',
                  switch_if='若中路有人留住对手且搭档能回城，再过河', fact_refs=refs[:])
    answer['lane_plan']['destination_choice'] = choice
    for fid in refs:
        answer['facts_used'].append(dict(fact_id=fid, value=frame['facts'][fid]['value']))
    result = validate_decision(answer, frame)
    assert result['status'] == 'PASS', result['errors']
    assert choice['why'] in render_decision(answer, result)
    assert 'destination_choice' not in output_schema(old['frame'])['properties']['lane_plan']['properties']
    assert bind_round(bundle, 'bot', 'dragon', 5, roam_actors=roles) == bundle
    for bad in ({'ally_mid':'self'}, {'enemy_mid':'m'}, {'ally_mid':'m', 'ally_jungle':'m'}):
        with pytest.raises(ValueError, match='invalid_roam_actors'):
            bind_round(bundle, 'bot', 'dragon', 5, roam_actors=bad)
    with pytest.raises(ValueError, match='different_roam_actors'):
        bind_round(bundle, 'bot', 'dragon', 5, roam_actors={'ally_mid':'j', 'ally_jungle':'m'})
    choice['fact_refs'].pop()
    assert validate_decision(answer, frame)['status'] == 'FAIL'
    choice.update(fact_refs=refs, alternative=choice['preferred'])
    assert validate_decision(answer, frame)['status'] == 'FAIL'


def test_support_wire_requires_plan_tool_and_preserves_both_enemy_roles(scenario):
    bundle, answer, _ = scenario
    schema = output_schema(bundle['frame'])
    req = dict(messages=model_messages(bundle, schema), tools=ROUND_TOOLS, response_schema=schema)
    assert 'support_lane_opportunity' in req['messages'][0]['content']
    record(req, 'compare_round_options')
    _, fmt = prepare_round_request(req, remaining_calls=2)
    tool = fmt['properties']['tool_requests']['items']['properties']['name']
    assert tool['enum'] == ['review_round_plan']
    record(req, 'review_round_plan', q='q2')
    _, fmt = prepare_round_request(req, remaining_calls=1)
    fields = fmt['properties']['answer']['properties']
    assert 'enemy_support' in fields['role_assignments']['required']
    assert fields['lane_plan']['properties']['roam']['properties']['wave_number'] == {'type': 'null'}
    wire = data(answer)
    wire['answer']['role_assignments']['enemy_support'] = answer['role_assignments'][-1]
    assert expand_round_response(req, wire)['answer'] == answer
    wire['answer']['role_assignments']['enemy_support'] = answer['role_assignments'][2]
    with pytest.raises(ValueError, match='invalid_selected_actor'):
        expand_round_response(req, wire)
