from copy import deepcopy
import pytest
from lol_coach.round_boundaries import BoundaryTracker
from lol_coach.reasoning_frame import digest

def bundle(t,values,sha='a'*64):
    facts={str(i):dict(entity_id=e,field=f,value=v,observed_at_seconds=obs,
        temporal_scope=scope) for i,(e,f,v,obs,scope) in enumerate(values)}
    frame=dict(schema='decision-frame/v1',decision=dict(build='16.20.824.8524',observer_team_id=100,
        player_entity_id='self',at_seconds=t),facts=facts,task={},input_policy=[])
    frame['frame_id']='frame_'+digest(frame)[:24]
    return dict(schema='reasoning-bundle/v1',frame=frame,audit=dict(source_replay_sha256=sha))

def test_zero_tower_candidate_has_only_present_refs_and_is_not_verdict():
    tracker=BoundaryTracker();a=bundle(1,[('tower','tower_health',10,1,'observed_sample')]);b=bundle(2,[('tower','tower_health',0,2,'observed_sample')])
    before=deepcopy([a,b]);assert tracker.feed(a) is None
    result=tracker.feed(b)
    assert result['reasons'][0]['reason']=='observed_zero_tower_health'
    assert result['actual_round_boundary'] is None and not result['timing_calculations_used']
    assert [a,b]==before
    assert tracker.feed(bundle(3,[('tower','tower_health',0,3,'observed_sample')])) is None

def test_absence_and_last_seen_zero_do_not_prove_death():
    tracker=BoundaryTracker();tracker.feed(bundle(1,[('enemy','health',100,1,'observed_sample')]))
    assert tracker.feed(bundle(2,[])) is None
    assert tracker.feed(bundle(3,[('enemy','health',0,1,'last_seen_sample')])) is None

def test_visibility_is_information_change_not_enemy_position():
    tracker=BoundaryTracker();tracker.feed(bundle(1,[('enemy','visibility',True,1,'visibility_policy')]))
    c=tracker.feed(bundle(2,[('enemy','visibility',False,2,'visibility_policy')]))
    assert c['reasons'][0]['reason']=='visibility_changed_reassess_information'

def test_cross_source_future_and_reverse_frames_rejected():
    tracker=BoundaryTracker();tracker.feed(bundle(1,[]))
    for b in [bundle(2,[],sha='b'*64),bundle(0,[]),bundle(2,[('a','health',0,3,'observed_sample')])]:
        with pytest.raises(ValueError):tracker.feed(b)

def test_prefix_results_identical_after_unseen_future_append():
    rows=[bundle(1,[]),bundle(2,[('a','public_kill_feed',{'victim':'x'},2,'historical_event_not_current_death_state')]),bundle(3,[])]
    a=BoundaryTracker();b=BoundaryTracker()
    assert [a.feed(x) for x in rows[:2]]==[b.feed(x) for x in rows][:2]

def test_lane_coordinates_and_reordered_counts_do_not_create_boundaries():
    counts=[dict(team_id=100,kind='melee',count=3),dict(team_id=200,kind='ranged',count=2)]
    tracker=BoundaryTracker();tracker.feed(bundle(1,[('lane','lane_current_units_and_groups',dict(counts=counts,position=1),1,'estimate')]))
    assert tracker.feed(bundle(2,[('lane','lane_current_units_and_groups',dict(counts=list(reversed(counts)),position=999),2,'estimate')])) is None
