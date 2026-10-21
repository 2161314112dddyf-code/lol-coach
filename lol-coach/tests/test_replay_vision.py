"""Synthetic safety cases for visibility and hidden/future-state exclusion."""
import pytest
from lol_coach.replay_vision import decode_payload,visibility_at,intervals,known_enemy_state,validate_cutoff


def event(t,visible,team=100,offset=1,entity='enemy'):
    return dict(time_seconds=t,visible=visible,observer_team_id=team,entity_id=entity,
                source={'chunk':1,'decompressed_offset':offset})


def update(t,values,offset=2,entity='enemy'):
    return dict(time_seconds=t,values=values,entity_id=entity,source={'chunk':1,'decompressed_offset':offset})


def test_direction_and_observer_are_separate():
    assert decode_payload(0x3cd,bytes.fromhex('a0f5'))['visible'] is False
    assert decode_payload(0x484,bytes.fromhex('a0f5'))['visible'] is True
    assert decode_payload(0x484,bytes.fromhex('a0f5'))['observer_team_id']==200
    assert decode_payload(0x484,bytes.fromhex('a0c5'))['observer_team_id']==100


@pytest.mark.parametrize('payload',[b'',b'\xa0',b'\xa0\xf5\x00',b'\xa0\x00'])
def test_unknown_or_truncated_payload_rejected(payload):
    with pytest.raises(ValueError):decode_payload(0x484,payload)


def test_wrong_version_and_opcode_rejected():
    with pytest.raises(ValueError):decode_payload(0x484,b'\xa0\xf5',version='16.21')
    with pytest.raises(ValueError):decode_payload(0x3df,b'\xa0\xf5')


def test_initial_unknown_and_observer_isolation():
    rows=[event(10,True,200)]
    assert visibility_at(rows,9,200,['enemy'])['enemy']['visible'] is None
    assert visibility_at(rows,11,100,['enemy'])['enemy']['visible'] is None
    assert visibility_at(rows,10,200,['enemy'])['enemy']['visible'] is True


def test_intervals_have_unknown_prefix_and_exact_half_open_boundary():
    rows=[event(2,True),event(5,False)]
    result=[r for r in intervals(rows,['enemy'],8) if r['observer_team_id']==100]
    assert [(x['start_seconds'],x['end_seconds'],x['visible']) for x in result]==[(0,2,None),(2,5,True),(5,8,False)]
    assert result[-1]['right_censored'] and result[-1]['end_event'] is None
    assert visibility_at(rows,5,100,['enemy'])['enemy']['visible'] is False


def test_hidden_updates_not_last_known_and_reentry_requires_fresh_sample():
    events=[event(2,True),event(4,False),event(8,True)]
    updates=[update(1,{'health':1000}),update(3,{'health':500}),update(6,{'health':9999})]
    hidden=known_enemy_state(events,updates,7,100,['enemy'])['enemy']
    assert hidden['current_observed'] is None
    assert hidden['last_observed']['health']['value']==500
    reentered=known_enemy_state(events,updates,8,100,['enemy'])['enemy']
    assert reentered['current_observed']=={}
    assert reentered['last_observed']['health']['observed_at_seconds']==3


def test_economy_and_unlisted_fields_never_exposed():
    state=known_enemy_state([event(0,True)],[update(1,dict(health=400,level=5,current_gold=9,total_gold=10,experience=11,secret=12))],2,100,['enemy'])['enemy']
    assert set(state['current_observed'])=={'health','level'}
    assert set(state['last_observed'])=={'health','level'}


def test_future_update_and_future_visibility_do_not_change_prefix():
    rows=[event(0,True),event(9,False)]
    updates=[update(1,{'health':20}),update(8,{'health':99})]
    result=known_enemy_state(rows,updates,5,100,['enemy'])['enemy']
    assert result['visible'] is True and result['current_observed']['health']['value']==20
    assert result['last_transition']['time_seconds']==0


def test_packet_order_within_timestamp_prevents_hidden_sample_leak():
    rows=[event(2,True,offset=10)]
    updates=[update(2,{'health':99},offset=9),update(2,{'resource':40},offset=11)]
    state=known_enemy_state(rows,updates,2,100,['enemy'])['enemy']
    assert 'health' not in state['last_observed']
    assert state['current_observed']['resource']['value']==40


def test_malformed_event_invalidates_prior_state():
    rows=[event(0,True),event(2,None,team=None)]
    state=known_enemy_state(rows,[update(1,{'health':90}),update(3,{'health':10})],4,100,['enemy'])['enemy']
    assert state['visible'] is None and state['current_observed'] is None
    assert state['last_observed']['health']['value']==90


def test_same_timestamp_last_transition_wins_in_intervals_and_query():
    rows=[event(2,True,offset=1),event(2,False,offset=3)]
    state=visibility_at(rows,2,100,['enemy'])['enemy']
    assert state['visible'] is False
    assert [(x['start_seconds'],x['end_seconds'],x['visible']) for x in intervals(rows,['enemy'],3) if x['observer_team_id']==100]==[(0,2,None),(2,3,False)]


@pytest.mark.parametrize('at',[-1,float('nan'),float('inf'),11])
def test_invalid_cutoff_rejected(at):
    with pytest.raises(ValueError):validate_cutoff(at,10)


def test_invalid_observer_rejected():
    with pytest.raises(ValueError):visibility_at([],0,300,['enemy'])
    with pytest.raises(ValueError):known_enemy_state([],[],0,300,['enemy'])
