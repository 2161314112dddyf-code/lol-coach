"""Synthetic safety checks. Real replay comparisons are a separate report."""
import struct
import pytest

from lol_coach.replay_state import (decode_group, decode_payload, floating,
                                   inverse_table, prefix_state, varuint)


def wire(body,tail=b'\x99'*9):
    inverse=inverse_table()
    table=bytes(inverse.index(i) for i in range(256))
    assert len(body)<128
    return (b'\0\0'+bytes([len(body)])+body).translate(table)+tail


def record(data,mask=3):
    return b'\x20'+struct.pack('<I',0x40000034)+struct.pack('<I',mask)+bytes([len(data)])+data


def test_values_and_offsets_not_from_tail():
    result=decode_payload(wire(record(struct.pack('<ff',123.5,900))))
    group=result['records'][0]['groups'][0]
    assert group['fields']['health']['value']==123.5
    assert group['fields']['max_health']['value']==900
    assert group['payload_offset']==13
    assert result['opaque_tail_hex']=='99'*9


def test_zero_is_one_byte_and_escape_preserves_literal_ff():
    assert floating(b'\xff',0)==(0.0,1)
    raw=bytes.fromhex('ff000044')
    assert floating(b'\xfe'+raw,0)==(struct.unpack('<f',raw)[0],5)


@pytest.mark.parametrize('payload',[b'',b'\xfe',b'\xfe\x00\x00',b'\x00\x00'])
def test_truncated_float_rejected(payload):
    with pytest.raises(ValueError):floating(payload,0)


def test_unknown_economy_suffix_is_not_named_or_consumed():
    data=struct.pack('<ff',20,100)+b'\x7f'
    fields,consumed=decode_group(1,0x103,data)
    assert set(fields)=={'current_gold','total_gold'}
    assert consumed==8


def test_missing_fields_are_absent():
    fields,_=decode_group(32,1,b'\xff')
    assert fields['health']['value']==0
    assert 'max_health' not in fields and 'resource' not in fields


def test_malformed_group_does_not_emit_partial_named_values():
    result=decode_payload(wire(record(struct.pack('<f',500),mask=3)))
    group=result['records'][0]['groups'][0]
    assert group['fields']=={}
    assert group['error']=='Truncated float'


@pytest.mark.parametrize('body',[
    b'\x20',
    b'\x80'+b'\0'*4,
    b'\x20'+b'\0'*4+b'\x01\0\0\0\x08'+b'\0'*4,
])
def test_structural_truncation_or_wrapper_rejected(body):
    with pytest.raises(ValueError):decode_payload(wire(body))


def test_wrong_version_rejected():
    with pytest.raises(ValueError,match='version'):
        decode_payload(wire(record(b'\xff',1)),version='16.15')


@pytest.mark.parametrize('data',[b'\x80',b'\x80\x00',b'\xff\xff\xff\xff\x10'])
def test_bad_length_varuint_rejected(data):
    with pytest.raises(ValueError):varuint(data,0)


def test_prefix_never_reads_later_updates():
    updates=[dict(time_seconds=10,entity_id='A',values={'health':12},source={'offset':1}),
             dict(time_seconds=20,entity_id='A',values={'health':0,'current_gold':50},source={'offset':2})]
    state=prefix_state(updates,15)
    assert state['actors']['A']['health']['value']==12
    assert 'current_gold' not in state['actors']['A']
    assert not state['decision_input_eligible']


@pytest.mark.parametrize('cutoff',[-1,float('nan'),float('inf')])
def test_invalid_cutoff_rejected(cutoff):
    with pytest.raises(ValueError):prefix_state([],cutoff)
