"""Recorded packet regression and synthetic failure/causality checks, not UI validation."""
import copy
import struct
import pytest
from lol_coach.turret_identity import decode_name,health_fields,load_profile,prefix_state

# 0x40000032 was excluded from the byte-table fitting set.
HELD_OUT=bytes.fromhex('79d4ff4c4b233865766876656868f3236838680b38760f38b7853ab78057381985b7b7d057f35b494d59b69a988e98e2acee626d')
SHORT_HEADER=bytes.fromhex('6934f64b233865766876656868f3236838680b38760f38b7853ab78057381985b7b7d057f35b494d59b69a988e98e2acee626d')
UNKNOWN_MODE=bytes.fromhex('76b0f84caf4e80e3da48b348fb6ef4ef21dab84e88f25348533f216eda4880dae2f6dab3676d')


@pytest.mark.parametrize('packet',[HELD_OUT,SHORT_HEADER])
def test_recorded_heldout_tower_name(packet):
    r=decode_name(packet)
    assert r['name']=='Turret_TOrder_L1_P2_2032291219_0'
    assert (r['team'],r['role'],r['static_object_hash'])==(100,'HA_Inhibitor','{79224d93}')
    assert r['map_id_decoded'] is None and r['mode_decoded'] is None


@pytest.mark.parametrize('packet',[b'',HELD_OUT[:5],HELD_OUT[:30],UNKNOWN_MODE,HELD_OUT[:15]+b'\x00'+HELD_OUT[16:]])
def test_unknown_or_truncated_names_refused(packet):
    with pytest.raises(ValueError):decode_name(packet)


def test_wrong_build_refused():
    with pytest.raises(ValueError,match='version'):decode_name(HELD_OUT,version='16.21')


def test_static_team_conflict_refused():
    p=copy.deepcopy(load_profile())
    for row in p['static_candidates']:
        if row['name']=='Turret_TOrder_L1_P2_2032291219_0':row['explicit_reference_team']=200
    with pytest.raises(ValueError,match='team'):decode_name(HELD_OUT,profile=p)


def test_class_layout_uses_tower_group32_not_other_groups():
    record={'groups':[{'group':4,'decoded_data_hex':'00004040','field_mask':1,'payload_offset':10},
        {'group':32,'decoded_data_hex':(b'\xff'+struct.pack('<f',2550)).hex(),'field_mask':3,'payload_offset':20}]}
    fields,evidence=health_fields(record)
    assert fields=={'health':0,'max_health':2550}
    assert evidence[0]['decoded_payload_offset']==20
    assert evidence[1]['decoded_payload_offset']==21


def test_prefix_does_not_backfill_identity_health_or_future_destruction():
    b={'identity_events':[{'entity_id':'tower','time_seconds':120}],
       'health_samples':[{'entity_id':'tower','time_seconds':0,'values':{'health':9999},'source':{}},
                         {'entity_id':'tower','time_seconds':150,'values':{'health':100},'source':{}}],
       'destruction_events':[{'entity_id':'tower','time_seconds':200}]}
    assert prefix_state(b,119)['objects']=={}
    r=prefix_state(b,120)
    assert r['objects']['tower']['latest_health']=={}
    assert r['objects']['tower']['destruction'] is None and not r['decision_input_eligible']
    assert prefix_state(b,151)['objects']['tower']['latest_health']['health']['value']==100


@pytest.mark.parametrize('t',[-1,float('nan'),float('inf')])
def test_bad_cutoffs_refused(t):
    with pytest.raises(ValueError):prefix_state({},t)
