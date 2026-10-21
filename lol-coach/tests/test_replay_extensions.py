"""Synthetic boundary tests; real packet/semantic checks live in reports."""
import struct
import pytest

from lol_coach.replay_extensions import inventory_checkpoint, attribute_group, checkpoint_profile


def envelope(records, prefix=b'\x4d\x38\x32'):
    return prefix + b''.join(records)


EMPTY = [bytes.fromhex(x) for x in ('c5efd5e8','c5ffd5e84c4434','c5ffd5e84c7434','c5ffd5e84c6434f0')]


def test_omitted_record_never_becomes_empty_slot_zero():
    result=inventory_checkpoint(envelope(EMPTY))
    assert result['omitted_records'][0]['slot'] is None
    assert [i['slot'] for i in result['items']]==[1,2,3]
    assert result['effective_inventory_time'] is None
    assert result['decision_input_eligible'] is False


def test_known_item_from_already_established_bytes():
    p=checkpoint_profile()
    assert p['items']['cc59']==dict(item_id=2007,name='Disabled Recall')
    assert p['items']['6159']==dict(item_id=2001,name='Recall')


def test_extended_record_preserves_opaque_prefix_and_suffix():
    records=EMPTY[:3]+[bytes.fromhex('c4ffa5e8696902ee4c6434f032a82c24')]
    item=inventory_checkpoint(envelope(records))['items'][-1]
    assert item['slot']==3
    assert item['opaque_extension_prefix_hex']=='696902ee'
    assert item['opaque_extension_suffix_hex']=='32a82c24'


def test_observed_extended_envelope():
    result=inventory_checkpoint(envelope(EMPTY,bytes.fromhex('4d3021edbfa13032')))
    assert result['opaque_envelope_hex']=='4d3021edbfa130'


@pytest.mark.parametrize('records', [EMPTY[:3],EMPTY+[EMPTY[-1]],EMPTY[:3]+[EMPTY[2]],
    [bytes.fromhex('c5efd5e800')]+EMPTY[1:],EMPTY[:3]+[bytes.fromhex('c4ff05e84c6434f0')]])
def test_ambiguous_or_unobserved_records_rejected(records):
    with pytest.raises(ValueError):inventory_checkpoint(envelope(records))


def test_version_guard():
    with pytest.raises(ValueError):inventory_checkpoint(envelope(EMPTY),version='other')
    with pytest.raises(ValueError):attribute_group(dict(group=4),version='other')


def test_attribute_mixed_layout_preserves_unknown_fields():
    group=dict(group=4,field_mask=(1<<1)|(1<<7)|(1<<14),payload_offset=50,
        decoded_data_hex=(b'\x04'+struct.pack('<ff',-2,45)).hex())
    rows=attribute_group(group)
    assert [(r['bit'],r['value']) for r in rows]==[(1,4),(7,-2),(14,45)]
    assert rows[0]['candidate_name'] is None
    assert rows[1]['decoded_payload_offset']==51


@pytest.mark.parametrize('group', [dict(group=32,field_mask=1,decoded_data_hex='ff',payload_offset=0),
    dict(group=4,field_mask=8,decoded_data_hex='00',payload_offset=0),
    dict(group=4,field_mask=8,decoded_data_hex='ffff',payload_offset=0)])
def test_attribute_layout_is_not_generic_or_silently_truncated(group):
    with pytest.raises(ValueError):attribute_group(group)
