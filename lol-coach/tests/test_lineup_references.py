from copy import deepcopy
import pytest
from test_round_boundaries import bundle
from lol_coach.lineup_references import attach_lineup_references
from lol_coach.reasoning_frame import digest,lookup_reference


def fixture():
    b=bundle(10,[]);b['frame']['lineup']=[dict(entity_id='a',champion='A',allied_ids=[],opponent_ids=['b']),dict(entity_id='b',champion='B',allied_ids=[],opponent_ids=['a'])]
    b['frame']['references']={};b['reference_library']={}
    b['frame']['frame_id']='frame_'+digest({k:v for k,v in b['frame'].items() if k!='frame_id'})[:24]
    m=dict(schema='champion-mechanisms/v1',patch='16.20.1',sources={'A':dict(url='synthetic',sha256='a'*64)},
        interactions=[dict(id='test',participants=['A','B'],relationship='opponent',summary_zh='synthetic',evidence=[dict(source='A')],requires={'active':True})])
    return b,m


def test_pair_binding_static_reference_and_input_preserved():
    b,m=fixture();original=deepcopy(b);r=attach_lineup_references(b,m);rid=next(iter(r['frame']['references']))
    d=lookup_reference(r,rid);assert d['current_applicability'] is None and d['current_conditions'] is None
    assert r['frame']['facts']==b['frame']['facts'] and b==original
    r['reference_library'][rid]['current_applicability']=True
    with pytest.raises(ValueError):lookup_reference(r,rid)


def test_wrong_relationship_or_champion_is_not_linked():
    b,m=fixture();m['interactions'][0]['relationship']='ally';assert attach_lineup_references(b,m)['frame']['references']=={}
    m['interactions'][0]['participants'][1]='Missing';assert attach_lineup_references(b,m)['frame']['references']=={}


def test_new_build_does_not_inherit_old_profile():
    b,m=fixture();b['frame']['decision']['build']='16.21.829.9102'
    b['frame']['frame_id']='frame_'+digest({k:v for k,v in b['frame'].items() if k!='frame_id'})[:24]
    with pytest.raises(ValueError):attach_lineup_references(b,m)
