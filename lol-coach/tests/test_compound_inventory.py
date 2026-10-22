"""Synthetic contract tests; the real replay checks are a separate script."""
import struct
import pytest

from lol_coach.compound_inventory import decode_inventory, ENCODING_TABLE, unpack_array


def packet(body, tail=b''):
    n = len(body)
    length = bytearray()
    while n >= 128:
        length.append((n & 127)|128)
        n >>= 7
    length.append(n)
    encoded = body.translate(ENCODING_TABLE)
    wire = bytearray(len(body))
    split = (len(body)+1)//2
    wire[::2] = encoded[:split]
    wire[1::2] = encoded[split:][::-1]
    return bytes([0x4e if tail else 0x4c])+bytes(length).translate(ENCODING_TABLE)+wire+tail


def item(slot, identity, stacks=1, charges=0, stats=()):
    out = bytearray(33+8*len(stats))
    struct.pack_into('<BBBHIf',out,0,0,slot,stacks,charges,identity,400.)
    struct.pack_into('<I',out,22,len(stats))
    for i,(key,value) in enumerate(stats):
        struct.pack_into('<If',out,26+8*i,key,value)
    return bytes(out)


def test_empty_update_does_not_erase_omitted_slots():
    result = decode_inventory(bytes.fromhex('4ce1e2'))
    assert result['items'] == []
    assert 'omitted_slots_are_not_empty' in result['update_mode']
    assert not result['complete_inventory_state']


def test_item_growth_map_keeps_next_slot_aligned():
    data = packet(b'\x02'+item(0,3070,charges=130,stats=[(56,130.)])+item(6,0,stacks=0),b'\x00'*13)
    result = decode_inventory(data)
    first, second = result['items']
    assert (first['item_id'],first['stack_count'],first['charge_count']) == (3070,1,130)
    assert first['stat_values'] == [dict(key=56,value=130.,semantic_name=None)]
    assert second['slot'] == 6 and second['empty']
    assert second['decoded_offset'] == first['decoded_end']


def test_long_array_and_uninterpreted_remainder_are_preserved():
    body = b'\x01'+item(2,2031,charges=2)+bytes(range(150))
    data = packet(body,b'\x12'*13)
    assert unpack_array(data)[0] == body
    assert decode_inventory(data)['uninterpreted_state_hex'] == bytes(range(150)).hex()


@pytest.mark.parametrize('bad', [b'', b'\x4e', bytes.fromhex('4ce1'), bytes.fromhex('4ee1e2')])
def test_bad_array_boundaries_fail(bad):
    with pytest.raises(ValueError):
        decode_inventory(bad)


def test_invalid_stat_count_does_not_eat_next_record():
    raw = bytearray(item(0,3070))
    struct.pack_into('<I',raw,22,20)
    with pytest.raises(ValueError,match='stat map'):
        decode_inventory(packet(b'\x01'+raw))


def test_version_gate_and_duplicate_slot():
    with pytest.raises(ValueError,match='build'):
        decode_inventory(bytes.fromhex('4ce1e2'),version='16.21')
    with pytest.raises(ValueError,match='slot'):
        decode_inventory(packet(b'\x02'+item(1,1036)+item(1,1036)))
