from copy import deepcopy
import pytest
from lol_coach.boundary_dataset import audit_cases
from lol_coach.reasoning_frame import digest


def case(cid='one',split='unassigned'):
    frame=dict(decision=dict(at_seconds=2),facts={'f':dict(observed_at_seconds=2)},task={})
    frame['frame_id']='frame_'+digest(frame)[:24]
    return dict(schema='round-boundary-review-case/v1',frame=frame,
        candidate=dict(candidate_id=cid,frame_id=frame['frame_id'],at_seconds=2,reasons=[dict(current_fact_id='f')],actual_round_boundary=None,tactical_correctness=None),
        future_outcome_included=False,label=None,split_group='a'*64,split=split)


def test_no_labels_never_produce_accuracy():
    report=audit_cases([case()]);assert report['candidate_usefulness_rate'] is None
    assert report['evaluation_status']=='INSUFFICIENT_EVIDENCE' and report['training_ready'] is False


def test_game_group_cannot_cross_splits():
    with pytest.raises(ValueError,match='crosses splits'):audit_cases([case(split='train'),case('two',split='test')])


def test_only_explicit_bound_labels_count_and_no_recall_claim():
    c=case();label=dict(candidate_id='one',frame_id=c['frame']['frame_id'],author='synthetic-test',useful_reconsideration=True)
    report=audit_cases([c],[label]);assert report['candidate_usefulness_rate']==1 and report['recall'] is None
    bad=deepcopy(label);bad['frame_id']='another'
    with pytest.raises(ValueError):audit_cases([c],[bad])
    with pytest.raises(ValueError):audit_cases([c],[label,label])


def test_future_fact_hash_change_and_unknown_reference_rejected():
    c=case();c['frame']['facts']['f']['observed_at_seconds']=3
    with pytest.raises(ValueError):audit_cases([c])
    c['frame']['frame_id']='frame_'+digest({k:v for k,v in c['frame'].items() if k!='frame_id'})[:24]
    c['candidate']['frame_id']=c['frame']['frame_id']
    with pytest.raises(ValueError,match='Future'):audit_cases([c])
    c=case();c['candidate']['reasons'][0]['current_fact_id']='unknown'
    with pytest.raises(ValueError):audit_cases([c])
