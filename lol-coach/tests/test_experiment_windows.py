from copy import deepcopy
import math
import pytest
from lol_coach.experiment_windows import research_windows,repeated_activity_pairs

def event(i,t,actor='a',stream=1):
    return dict(event_id=str(i),record_index=i,time_seconds=t,entity_id=actor,
        category='spell_activity',source=dict(stream=stream,chunk=1,decompressed_offset=i),
        data=dict(spell_name='Q'),rejected=False)

def test_research_windows_keep_unknowns_and_do_not_mutate():
    rows=[event(0,0),event(1,5),event(2,7),event(3,6,'b'),event(4,6,stream=2),event(5,11)]
    original=deepcopy(rows);out=research_windows(rows,['1'])[0]
    assert [r['event_id'] for r in out['rows']]==['0','1','2']
    assert out['includes_future_relative_to_anchor'] and not out['decision_input_eligible']
    assert all(v is None for v in out['labels'].values())
    out['rows'][0]['data']['spell_name']='R';assert rows==original

def test_activity_gap_is_not_cooldown_and_same_name_other_actor_is_separate():
    pairs=repeated_activity_pairs([event(1,10),event(2,11,'b'),event(3,13),event(4,12,stream=2)])
    assert len(pairs)==1 and pairs[0]['activity_gap_seconds']==3
    assert pairs[0]['cooldown_seconds'] is None and pairs[0]['successful_casts'] is None

@pytest.mark.parametrize('radius',[True,0,-1,math.nan,math.inf])
def test_bad_radius(radius):
    with pytest.raises(ValueError):research_windows([event(0,0)],['0'],radius=radius)

def test_duplicate_and_checkpoint_anchor_rejected():
    with pytest.raises(ValueError):research_windows([event(0,0),event(0,0)],['0'])
    with pytest.raises(ValueError):research_windows([event(0,0,stream=2)],['0'])

def test_distant_inventory_brackets_are_research_context_not_invented_current_state():
    before=event(0,0);before.update(category='inventory',data={'kind':'inventory_snapshot'})
    after=event(2,100);after.update(category='inventory',data={'kind':'inventory_snapshot'})
    w=research_windows([after,event(1,50),before],['1'])[0]
    assert len(w['rows'])==1
    assert w['inventory_brackets']['previous']['time_seconds']==0
    assert w['inventory_brackets']['following']['time_seconds']==100
    assert w['labels']['actual_item_slot'] is None
