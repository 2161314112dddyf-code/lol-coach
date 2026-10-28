"""Controlled fixture checks; no claim that model tactics are correct."""
from copy import deepcopy
import json

import pytest

from lol_coach.decision_contract import output_schema
from lol_coach.reasoning_frame import model_messages
import lol_coach.reasoning_simulation as sim


def differences(a,b,path=''):
    if isinstance(a,dict) and isinstance(b,dict):
        result=[]
        for key in sorted(set(a)|set(b)):
            if key not in a or key not in b:result.append(path+key)
            else:result+=differences(a[key],b[key],path+key+'.')
        return result
    return [] if a==b else [path.rstrip('.')]


@pytest.mark.parametrize('pair',list(sim.PAIR_SPECS))
def test_each_pair_changes_one_semantic_variable(pair):
    cases=sim.build_cases();a=deepcopy(cases[pair+'A']);b=deepcopy(cases[pair+'B'])
    a['frame'].pop('frame_id');b['frame'].pop('frame_id')
    paths=differences(a,b)
    expected=sim.PAIR_SPECS[pair][1]
    if pair=='C4':assert paths==[expected]
    elif pair=='C6':
        assert set(paths)=={'frame.'+expected,'reference_library.principle:coordination.source_environment'}
    else:assert paths==['frame.'+expected]


def test_hidden_position_never_changes_model_messages():
    cases=sim.build_cases()
    a=model_messages(cases['C4A'],output_schema());b=model_messages(cases['C4B'],output_schema())
    assert a==b
    assert 'omniscient_enemy_position' not in json.dumps(a)
    assert cases['C4A']['audit']!=cases['C4B']['audit']


def test_all_facts_are_explicit_synthetic_and_rubric_is_separate():
    cases=sim.build_cases();rubric=sim.build_rubric()
    assert len(cases)==14 and set(cases)==set(rubric['cases'])
    for cid,bundle in cases.items():
        assert bundle['audit']['real_replay_used'] is False
        assert all(f['evidence_level']=='synthetic_stipulated' for f in bundle['frame']['facts'].values())
        assert all(fid in bundle['frame']['facts'] for fid in rubric['cases'][cid]['required_fact_refs'])
        assert 'required_fact_refs' not in json.dumps(model_messages(bundle,output_schema()))
        assert 'forbidden' not in json.dumps(bundle)


def answer_for(frame):
    refs=list(frame['facts'])
    def option(oid):
        return dict(id=oid,action='合成候选'+oid,status='conditional',fact_refs=list(refs),
            reference_refs=[],preconditions=['确认可退出路径'],ally_requirements=[],
            enemy_responses=['对手可能反打'],time_budget=dict(travel_seconds=None,
                execution_seconds=None,exit_seconds=None,window_seconds=None,calculation_refs=[]),
            gains=['保留选择'],costs=['放弃位置收益'],end_state='新信息后重评',
            abort_signals=['出现新威胁'],assumptions=[])
    return dict(schema='round-decision/v1',frame_id=frame['frame_id'],objective='合成结构检查',
        facts_used=[dict(fact_id=fid,value=deepcopy(frame['facts'][fid]['value'])) for fid in refs],
        role_assignments=[dict(actor_id=h['entity_id'],role='待判断',fact_refs=[],assumptions=[])
                          for h in frame['lineup']],
        options=[option('a'),option('b')],recommendation=dict(preferred_option_id='a',
            fallback_option_id='b',confidence='conditional',why='有条件的选择',
            switch_conditions=['新信息改变约束']),open_questions=['退出条件是否具备'])


@pytest.fixture
def exported(tmp_path,monkeypatch):
    monkeypatch.setattr(sim,'ROOT',tmp_path)
    base=tmp_path/'data/private/reasoning_simulation'
    cases=base/'cases';sim.prepare_cases(cases)
    answers=base/'answers';answers.mkdir()
    return base,cases,answers


def test_prepare_is_reproducible_and_does_not_overwrite(exported):
    base,cases,_=exported
    sim.prepare_cases(base/'second')
    assert (cases/'manifest.json').read_bytes()==(base/'second/manifest.json').read_bytes()
    with pytest.raises(FileExistsError):sim.prepare_cases(cases)


def test_missing_answers_are_failures_not_skips(exported):
    base,cases,answers=exported
    result=sim.check_answers(cases,answers,base/'checked')
    assert result['status']=='FAIL' and len(result['cases'])==14
    assert all(r['contract_status']=='FAIL' for r in result['cases'])
    assert all(r['tactical_quality']=='not_evaluated' for r in result['cases'])


def test_valid_contract_never_becomes_tactical_pass(exported):
    base,cases,answers=exported
    for cid,bundle in sim.build_cases().items():
        (answers/(cid+'.json')).write_text(json.dumps(answer_for(bundle['frame']),ensure_ascii=False),encoding='utf-8')
    result=sim.check_answers(cases,answers,base/'checked')
    assert result['status']=='PASS'
    assert all(r['tactical_quality']=='not_evaluated' for r in result['cases'])
    assert len(result['cases_manifest_sha256'])==64
    assert set(result['checker_sources'])=={'validator','renderer','harness'}
    assert all(r['answer_sha256'] for r in result['cases'])


def test_critical_fact_must_be_copied_and_linked_to_decision(exported):
    base,cases,answers=exported
    answer=answer_for(sim.build_cases()['C1A']['frame'])
    for option in answer['options']:option['fact_refs'].remove('ally_action')
    (answers/'C1A.json').write_text(json.dumps(answer,ensure_ascii=False),encoding='utf-8')
    result=sim.check_answers(cases,answers,base/'checked')
    row=result['cases'][0]
    assert row['contract_status']=='PASS'
    assert row['critical_fact_coverage_status']=='FAIL'
    assert row['missing_critical_fact_refs']==['ally_action']


@pytest.mark.parametrize('raw',['{broken', '[]', '{"options":null}'])
def test_malformed_answer_retains_failure_report(exported,raw):
    base,cases,answers=exported
    (answers/'C1A.json').write_text(raw,encoding='utf-8')
    result=sim.check_answers(cases,answers,base/'checked')
    assert result['cases'][0]['contract_status']=='FAIL'
    assert (base/'checked/C1A/validation.json').exists()


def test_altered_input_rejected_before_creating_output(exported):
    base,cases,answers=exported
    path=cases/'C1A/bundle.json';path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='Frozen'):sim.check_answers(cases,answers,base/'checked')
    assert not (base/'checked').exists()


def test_output_must_stay_in_task_area(exported):
    base,_,_=exported
    with pytest.raises(ValueError,match='new child'):sim.prepare_cases(base.parent/'outside')


def test_original_twelve_case_export_remains_checkable(exported,monkeypatch):
    base,_,answers=exported
    old_cases={cid:bundle for cid,bundle in sim.build_cases().items() if not cid.startswith('C7')}
    old_rubric=sim.build_rubric()
    old_rubric['cases']={cid:row for cid,row in old_rubric['cases'].items() if cid in old_cases}
    with monkeypatch.context() as patch:
        patch.setattr(sim,'build_cases',lambda:deepcopy(old_cases))
        patch.setattr(sim,'build_rubric',lambda:deepcopy(old_rubric))
        sim.prepare_cases(base/'legacy')
    for cid,bundle in old_cases.items():
        (answers/(cid+'.json')).write_text(json.dumps(answer_for(bundle['frame']),ensure_ascii=False),encoding='utf-8')
    result=sim.check_answers(base/'legacy',answers,base/'legacy_checked')
    assert result['status']=='PASS' and len(result['cases'])==12
