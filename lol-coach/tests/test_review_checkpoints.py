from copy import deepcopy
import pytest
from test_round_boundaries import bundle
from lol_coach.review_checkpoints import CheckpointScheduler,prepare_checkpoint
from lol_coach.round_chain import _check_bundle


def test_initial_and_no_change_do_not_create_fixed_rounds():
    s=CheckpointScheduler(30);assert s.feed(bundle(0,[]))['selected']
    assert not s.feed(bundle(100,[]))['selected']


def test_changes_coalesce_without_losing_events():
    s=CheckpointScheduler(30);s.feed(bundle(0,[]))
    first=s.feed(bundle(5,[('a','public_kill_feed',1,5,'historical_event')]))
    assert not first['selected']
    b=bundle(30,[]);r=s.feed(b);assert r['selected'] and len(r['covered_candidates'])==1
    assert r['true_round_boundary'] is None and s.tail()==[]
    prepared=prepare_checkpoint(b,r);_check_bundle(prepared)
    assert prepared['frame']['facts']=={} and prepared['frame']['task']['review_checkpoint']['current_trigger_fact_ids']==[]


@pytest.mark.parametrize('entity,field',[('self','health'),('tower','tower_health')])
def test_urgent_zero_is_not_delayed(entity,field):
    s=CheckpointScheduler();s.feed(bundle(0,[]));r=s.feed(bundle(2,[(entity,field,0,2,'observed_sample')]))
    assert r['selected'] and r['selection_kind']=='urgent_observation'


def test_future_does_not_rewrite_checkpoint_and_input_is_immutable():
    a=CheckpointScheduler();b=CheckpointScheduler();x=bundle(0,[]);before=deepcopy(x)
    first=a.feed(x);frozen=deepcopy(first);assert first==b.feed(x)
    a.feed(bundle(40,[('self','health',0,40,'observed_sample')]))
    assert first==frozen
    assert x==before


def test_wrong_frame_and_bad_interval_rejected():
    for value in (0,-1,float('nan'),True):
        with pytest.raises(ValueError):CheckpointScheduler(value)
    s=CheckpointScheduler();selection=s.feed(bundle(0,[]))
    with pytest.raises(ValueError):prepare_checkpoint(bundle(1,[]),selection)


def test_scan_cutoff_flushes_tail_without_rewriting_previous_checkpoint():
    s=CheckpointScheduler();initial=s.feed(bundle(0,[]));saved=deepcopy(initial)
    last=bundle(5,[('a','public_kill_feed',1,5,'historical_event')]);assert not s.feed(last)['selected']
    with pytest.raises(ValueError):s.flush(bundle(6,[]))
    r=s.flush(last);assert r['selected'] and r['at_seconds']==5 and len(r['covered_candidates'])==1
    assert s.tail()==[] and s.flush(last) is None and initial==saved
