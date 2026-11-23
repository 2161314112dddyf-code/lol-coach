"""Synthetic boundary tests. These do not evaluate tactical model quality."""
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from lol_coach.decision_contract import output_schema, validate_decision
from lol_coach.execution_review import evidence_review, finish_execution_review
from lol_coach.personal_episode import (PersonalPathIndex, attach_personal_history,
    bind_personal_actions, personal_context, execution_evidence, event_review_times, refresh_identity)
from lol_coach.reasoning_frame import digest, model_messages
from lol_coach.reasoning_runner import run_reasoning
from lol_coach.round_model_format import prepare_round_request, expand_round_response
from lol_coach.round_tools import ROUND_TOOLS, bind_round, round_call
from test_round_agent_integration import round_answer
from test_round_chain import bundle_at
from test_round_model_format import data, record


def sample(at, x, target, actor=1):
    return dict(entity_id=actor, time_seconds=at, world_waypoints_xz=[[x,0],[target,0]],
                speed=350, source=dict(chunk=1,offset=int(at*1000),record_index=0))


def base(at=20):
    return refresh_identity(json.loads(json.dumps(bundle_at(at)).replace('"self"', '"0x1"')))


def pair():
    bound = bind_round(bundle_at(20), 'mid', 'dragon', 5)
    answer = round_answer(bound)
    bound = refresh_identity(json.loads(json.dumps(bound).replace('"self"','"0x1"')))
    answer = json.loads(json.dumps(answer).replace('"self"','"0x1"'))
    bound = bind_personal_actions(bound)
    answer['frame_id'] = bound['frame']['frame_id']
    answer['options'] = answer['options'][:2]
    for row, name in zip(answer['options'], ('continue_action','change_action')):
        row['id'] = name
    answer['recommendation'].update(preferred_option_id='continue_action',fallback_option_id='change_action')
    return bound, answer


def test_future_edits_cannot_change_personal_history_or_mcp():
    past = [sample(8,0,100),sample(10,20,200),sample(20,40,200),sample(19,900,1100,actor=2)]
    before = base()
    a = attach_personal_history(before, PersonalPathIndex('a'*64, past+[sample(20.001,1000,1100)]))
    b = attach_personal_history(before, PersonalPathIndex('a'*64, past+[sample(21,99999,99000)]))
    assert a == b and before == base()
    report = personal_context(a['frame'])
    assert len(report['samples']) == 2
    assert report['displacement_between_observed_endpoints'] == 20
    assert list(report['samples'].values())[-1]['value']['commanded_path_xz'][-1] == [200,0]
    assert attach_personal_history(a,PersonalPathIndex('a'*64,past)) == a


def test_coordination_followup_uses_addressed_ally_and_separates_sends_from_attention():
    from lol_coach.personal_episode import _coordination_followup
    frame = base()['frame']
    frame['lineup'][1]['entity_id'] = '0x2'
    index = PersonalPathIndex('a'*64, [sample(20, 1, 900, 2), sample(20.2, 2, 900, 2),
                                      sample(20.3, 3, 900, 2), sample(21, 5, 900, 2),
                                      sample(21.1, 8, 900, 2), sample(20.5, 3, 900, 3)])
    def ping(t, sender, team, kind):
        return dict(time_seconds=t, sender_entity_id=sender, team_id=team, kind=kind, channel='team',
                    source=dict(chunk=1, offset=int(t*100)))
    pings = dict(schema='review-ping-index/v1', source_sha256=index.source, build='synthetic',
                 status='verified', events=[
                     ping(20,'0x1',100,'push'), ping(20.2,'0x1',100,'push'),
                     ping(20.4,'0x2',100,'on_my_way'), ping(20.6,'0x2',100,'command'),
                     ping(20.7,'enemy',200,'retreat'), ping(21.1,'0x1',100,'assist_me')])
    rows, coverage = _coordination_followup(frame, index, ['0x2'], 21, pings)
    assert coverage == 'verified_sends_only'
    assert [(r['at'], r['observed_xz']) for r in rows if r['kind'] == 'ally_position_sample'] == [
        (20.2, [2, 0]), (21, [5, 0])]
    assert [(r['actor_id'], r['ping_kind']) for r in rows if r['kind'] == 'map_ping_sent'] == [
        ('0x1', 'push'), ('0x2', 'on_my_way')]
    with pytest.raises(ValueError, match='outside observer team'):
        _coordination_followup(frame, index, ['enemy'], 21, pings)
    with pytest.raises(ValueError, match='source mismatch'):
        _coordination_followup(frame, index, [], 21, dict(pings, source_sha256='b'*64))
    assert _coordination_followup(frame, index, [], 21, None) == ([], 'unavailable')


def test_empty_and_bounded_histories_preserve_unknown_and_endpoints():
    assert personal_context(attach_personal_history(base(),PersonalPathIndex('a'*64,[]))['frame'])[
        'displacement_between_observed_endpoints'] is None
    many = [sample(9+i/10,i,i+200) for i in range(111)]
    report = personal_context(attach_personal_history(base(),PersonalPathIndex('a'*64,many))['frame'])
    rows = list(report['samples'].values())
    assert len(rows)==16 and rows[0]['observed_at_seconds']==9 and rows[-1]['observed_at_seconds']==20


def test_mixed_replays_rejected():
    with pytest.raises(ValueError,match='source'):
        attach_personal_history(base(),PersonalPathIndex('b'*64,[]))


def test_new_action_contract_roundtrips_without_borrowing_route_timing():
    bound, answer = pair()
    assert validate_decision(answer,bound['frame'])['status']=='PASS'
    request = dict(messages=model_messages(bound,output_schema(bound['frame'])),tools=ROUND_TOOLS,
                   response_schema=output_schema(bound['frame']))
    record(request,'review_personal_action')
    _, schema = prepare_round_request(request)
    answer_schema = schema['anyOf'][0]['properties']['answer']
    assert set(answer_schema['properties']['options']['required']) == {'continue_action','change_action'}
    assert expand_round_response(request,data(answer)) == {'answer':answer}
    bad = deepcopy(answer)
    bad['options'][0]['id']='leave_now'
    assert validate_decision(bad,bound['frame'])['status']=='FAIL'


def test_new_mcp_tool_is_mandatory_and_scope_cannot_be_overridden():
    bound, answer = pair()
    with pytest.raises(ValueError):
        round_call(bound,'review_personal_action',{'at_seconds':22})
    replies = iter([{'answer':answer},{'tool_requests':[dict(id='p',name='review_personal_action',arguments={})]},
                    {'answer':answer}])
    result = run_reasoning(bound,lambda _:next(replies),round_tool_call=lambda n,a:round_call(bound,n,a))
    assert result['status']=='completed' and result['model_calls']==3


def test_execution_is_post_decision_and_bound_to_answer_and_available_time():
    bound, answer = pair()
    index = PersonalPathIndex('a'*64,[sample(20,0,100),sample(20.1,1,100),sample(21,2,100)])
    event = dict(time_seconds=19.9,available_at_seconds=20.424,event_id=1)
    before = deepcopy(bound)
    early = execution_evidence(bound,answer,index,20.423,[event])
    later = execution_evidence(bound,answer,index,20.424,[event])
    assert len(early['actual'])==1 and len(later['actual'])==2
    assert later['sealed_answer_sha256']==digest(answer) and bound==before
    assert later['unknown']==early['unknown']
    with pytest.raises(ValueError):
        execution_evidence(bound,answer,PersonalPathIndex('b'*64,[]),21)


def test_hindsight_contacts_use_only_same_team_opponent_receipts_in_the_sealed_window():
    from lol_coach.personal_episode import personal_contact_index
    bound, answer = pair()
    team = bound['frame']['decision']['observer_team_id']
    index = PersonalPathIndex('a'*64, [sample(19.9, 0, 300), sample(20.1, 0, 300)])
    entities = {'0x1': dict(name='Player', team_id=team)}
    vision = dict(source_sha256=index.source, end_seconds=21, entities=entities,
                  observations=[], enemy_positions_in_view=[])
    for i, (at, observer) in enumerate([(20, team), (20.2, team), (20.3, 300-team), (20.4, team)], 2):
        subject = 'entity:'+hex(i)
        entities[hex(i)] = dict(name=str(i), team_id=300-team)
        vision['observations'].append(dict(team_id=observer, mode='transition', subject=subject,
                                           time_seconds=at, visible=True))
        vision['enemy_positions_in_view'].append(dict(team_id=observer, subject=subject, time_seconds=at,
            xz=[100, 0], source=dict(offset=i), visibility_record=dict(offset=i+10)))
    contacts = personal_contact_index(index, vision, '0x1', team)
    before = deepcopy((bound, answer))
    early = execution_evidence(bound, answer, index, 20.3, contact_index=contacts)
    observed = [r for r in early['actual'].values() if r['kind'] == 'nearby_opponent_seen_by_team']
    assert [(r['at'], r['opponent_id']) for r in observed] == [(20.2, '0x3')]
    assert observed[0]['source']['team_visibility'] == dict(offset=13)
    later = execution_evidence(bound, answer, index, 20.4, contact_index=contacts)
    assert len(later['actual']) == len(early['actual'])+1
    assert before == (bound, answer)
    for override in [dict(team_id=300-team), dict(player_entity_id='0x5'), dict(source_sha256='b'*64)]:
        with pytest.raises(ValueError, match='contact perspective mismatch'):
            execution_evidence(bound, answer, index, 20.4, contact_index={**contacts, **override})
    with pytest.raises(ValueError, match='bound own-team actor'):
        personal_contact_index(index, vision, '0x1', 300-team)


def test_event_selection_uses_fractional_receipt_and_forward_command_only():
    rows=[sample(10,0,300),sample(10.25,10,-300),sample(11,0,300)]
    event=dict(time_seconds=10.2,available_at_seconds=10.424)
    a=event_review_times([],PersonalPathIndex('a'*64,rows),'0x1',10.5,[event])
    b=event_review_times([],PersonalPathIndex('a'*64,rows+[sample(19,200,-900)]),'0x1',10.5,[event])
    assert a==b and [r['at'] for r in a]==[10.25,10.424]
    assert not event_review_times([],PersonalPathIndex('a'*64,[]),'0x1',10.3,[event])


@pytest.mark.parametrize('bad', [dict(answer_sha256='wrong',accepted=True,issues=[]),
                              dict(accepted=True,issues=['conflict'])])
def test_evidence_review_cannot_accept_wrong_binding_or_inconsistent_verdict(bad):
    bound, answer=pair()
    result=dict(answer=answer,trace=[])
    bad.setdefault('answer_sha256',digest(answer))
    with pytest.raises(ValueError):
        evidence_review(bound,result,lambda _:bad)


def test_rejected_claim_is_repaired_in_same_frozen_context_and_never_sealed():
    bound, answer=pair()
    wrong=deepcopy(answer);wrong['recommendation']['why']='无证据必杀9999'
    replies=iter([{'answer':wrong},{'answer':answer}])
    reviews=[]
    def reviewer(candidate):
        accepted=candidate['answer']==answer
        reviews.append(candidate['answer'])
        return dict(answer_sha256=digest(candidate['answer']),accepted=accepted,
                    issues=[] if accepted else ['Synthetic reviewer rejects unsupported damage'])
    result=run_reasoning(bound,lambda _:next(replies),answer_review=reviewer)
    assert result['status']=='completed' and result['answer']==answer and len(reviews)==2
    assert any(e['event']=='validation' and e['result']['status']=='FAIL' for e in result['trace'])
    repeated=run_reasoning(bound,lambda _:{'answer':wrong},answer_review=reviewer)
    assert repeated['status']=='invalid_answer' and repeated['model_calls']==2


def test_hindsight_is_inaccessible_until_all_cards_sealed(tmp_path):
    (tmp_path/'manifest.json').write_text(json.dumps(dict(steps=[dict(status='completed'),dict(status='failed')])) )
    with pytest.raises(ValueError,match='all decisions'):
        finish_execution_review(tmp_path,PersonalPathIndex('a'*64,[]),SimpleNamespace())
    assert not (tmp_path/'execution-review.md').exists()


def test_review_adapter_uses_real_file_bridge_answer_envelope(tmp_path,monkeypatch):
    import lol_coach.file_model_bridge as bridge
    import lol_coach.execution_review as review
    def directory(path):
        path.mkdir();return path
    monkeypatch.setattr(bridge,'new_directory',directory)
    def factory(path,**kwargs):
        def respond(event):
            request=json.loads(open(event['request_path'],encoding='utf-8').read())['request']
            assert request['response_schema']['required']==['answer']
            bridge.atomic_json(event['response_path'],dict(request_id=event['request_id'],response=dict(answer=dict(ok=True))))
        return bridge.FileModelBridge(path,on_request=respond,timeout_seconds=1)
    monkeypatch.setattr(review,'file_generate',factory)
    generate=review.review_generator(tmp_path/'exchange',SimpleNamespace(backend='file',timeout=1))
    assert generate(dict(messages=[],tools=[],response_schema=dict(type='object'))) == dict(ok=True)


def test_nearby_appearance_waits_for_current_visible_sample_not_hidden_future():
    from lol_coach.personal_episode import nearby_threat_observations
    index=PersonalPathIndex('a'*64,[sample(10,0,300)])
    vision=dict(source_sha256='a'*64,observations=[dict(team_id=100,mode='transition',subject='enemy',
         time_seconds=10,visible=True)],enemy_positions_in_view=[dict(team_id=100,subject='enemy',time_seconds=10.1,xz=[200,0])])
    assert not nearby_threat_observations(index,vision,'0x1',100,10)
    visible=nearby_threat_observations(index,vision,'0x1',100,10.1)
    assert len(visible)==1 and visible[0]['at']==10.1
    assert not nearby_threat_observations(index,vision,'0x1',200,20)
    vision['enemy_positions_in_view'][0]['xz']=[9000,0]
    assert not nearby_threat_observations(index,vision,'0x1',100,20)


def test_local_review_preserves_both_provider_replies_on_repair(tmp_path,monkeypatch):
    import io
    import lol_coach.execution_review as review
    monkeypatch.setattr(review.urllib.request,'urlopen',lambda *a,**k:io.StringIO(
        json.dumps(dict(message=dict(content='{"accepted":true}')))))
    generate=review.review_generator(tmp_path,SimpleNamespace(backend='ollama',model='synthetic',port=1))
    request=dict(messages=[],tools=[],response_schema=dict(type='object'))
    assert generate(request)==generate(request)==dict(accepted=True)
    assert sorted(p.name for p in tmp_path.glob('provider-*.json'))==['provider-01.json','provider-02.json']


def test_same_second_decisions_have_distinct_visible_clocks():
    from scripts.run_review_agent import render_map_review
    from lol_coach.decision_contract import render_decision
    bundle,answer=pair()
    bundle['frame']['decision']['at_seconds']=20.4241333007812
    validation=validate_decision(answer,bundle['frame'])
    assert '00:20.424' in render_decision(answer,validation)
    rows=[dict(at_seconds=t,champion='Pantheon',player_entity_id='0x1',source_sha256='a'*64) for t in (750,750.4241333007812)]
    rendered=render_map_review(rows)
    assert '**12:30**' in rendered and '**12:30.424**' in rendered


def test_ordinary_checkpoint_does_not_assign_a_roam_or_display_team_instructions():
    from lol_coach.personal_episode import bind_personal_checkpoint
    from scripts.run_review_agent import render_map_review
    bundle, _ = pair()
    frame = bind_personal_checkpoint(bundle)['frame']
    assert frame['task']['team_coordination_trigger'] == dict(active=False, reasons=[], fact_ids=[])
    schema = output_schema(frame)
    assert {'team_coordination', 'lane_plan'}.isdisjoint(schema['properties'])
    assert '查看 review_round_plan.team_pings' not in model_messages({'frame':frame},schema)[0]['content']
    step = dict(champion='Pantheon',source_sha256='a'*64,at_seconds=20,
                coordination_trigger=frame['task']['team_coordination_trigger'],
                player_choice=dict(first_step='收下眼前残血兵。', switch_conditions=['对手抬手时后撤。']))
    report = render_map_review([step])
    assert '收下眼前残血兵' in report and '对手抬手时后撤' in report
    assert '怎么沟通' not in report and '队友' not in report and '未生成' not in report
