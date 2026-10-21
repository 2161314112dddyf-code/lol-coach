"""Synthetic timing/visibility policy boundaries for named enemy towers."""
import pytest
from lol_coach.replay_vision import VERSION
from lol_coach.tower_vision import enemy_tower_view


def fixtures():
    towers=dict(version=VERSION,source={'test':'synthetic'},identity_events=[
        dict(entity_id='enemy',time_seconds=2,identity={'team':200}),
        dict(entity_id='ally',time_seconds=0,identity={'team':100})],health_samples=[
        dict(entity_id='enemy',time_seconds=2,values={'health':100},source={'stream':1,'chunk':1,'offset':2}),
        dict(entity_id='enemy',time_seconds=3,values={'health':50},source={'stream':1,'chunk':1,'offset':4})])
    events=[dict(entity_id='enemy',time_seconds=t,observer_team_id=100,visible=v,
        source={'chunk':1,'decompressed_offset':o}) for t,v,o in [(1,True,1),(3,False,3),(4,True,5)]]
    return towers,dict(version=VERSION,source=towers['source'],events=events)


def test_future_identity_and_allies_excluded():
    t,v=fixtures();assert enemy_tower_view(t,v,1,100)['towers']=={}
    assert set(enemy_tower_view(t,v,2,100)['towers'])=={'enemy'}


def test_hidden_sample_and_reentry_not_reused():
    t,v=fixtures();hidden=enemy_tower_view(t,v,3,100)['towers']['enemy']
    assert hidden['current_observed'] is None
    assert hidden['last_observed']['health']['value']==100
    assert enemy_tower_view(t,v,4,100)['towers']['enemy']['current_observed']=={}


def test_keyframe_samples_not_promoted():
    t,v=fixtures();t['health_samples'][0]['source']['stream']=2
    assert enemy_tower_view(t,v,2,100)['towers']['enemy']['current_observed']=={}


def test_wrong_source_or_observer_rejected():
    t,v=fixtures()
    with pytest.raises(ValueError):enemy_tower_view(t,v,2,123)
    v['source']={'another':'replay'}
    with pytest.raises(ValueError):enemy_tower_view(t,v,2,100)
