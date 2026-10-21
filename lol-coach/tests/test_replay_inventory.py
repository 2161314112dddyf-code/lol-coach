"""Software safety checks; real packet fixtures do not prove all game semantics."""
import pytest
from lol_coach.replay_inventory import decode_payload,decode_raw,load_profile


def test_observed_update_labels_item_and_slot():
    result=decode_payload(0x25f,bytes.fromhex('373eb9231b8b6d34163220b5876246'))
    assert result['slot']==4 and result['item_id']==6653
    assert result['transaction_reason'] is None


def test_observed_zero_gold_branch():
    result=decode_payload(0x25f,bytes.fromhex('3f3bf73416168d667159'))
    assert result['slot']==2 and result['item_id']==2031
    assert result['gold_wire'] is None  # Not a fabricated current-gold value.


def test_observed_clear_does_not_invent_removed_item():
    result=decode_payload(0x132,bytes.fromhex('8c1d336ed1235e'))
    assert result['slot']==5 and 'item_id' not in result


def test_observed_variable_swap():
    result=decode_payload(0x66,bytes.fromhex('844608'))
    assert result['slot']==4 and result['other_slot']==3
    assert decode_raw(0x66,bytes.fromhex('844608'))['other_slot'] is None


def test_unknown_item_stays_unknown():
    profile=load_profile();profile['items']={}
    result=decode_payload(0x25f,bytes.fromhex('373eb9231b8b6d34163220b5876246'),profile=profile)
    assert result['item_id'] is None and result['item_wire']=='8762'


def test_special_prefix_kept_opaque():
    result=decode_payload(0x25f,bytes.fromhex('37910ab9fcbbcf35d07f1636b0b5434a'))
    assert result['item_id']==3003 and result['opaque_prefix_hex']=='d07f'


def test_unknown_stack_count_not_invented():
    result=decode_payload(0x25f,bytes.fromhex('36f9df8051695c34c3f51bdc'))
    assert result['count_candidate'] is None and result['count_wire']=='1b'


@pytest.mark.parametrize('opcode,wire',[(0x25f,'373eb9231b8b6d34163220b5876246'),(0x132,'8c1d336ed1235e'),(0x66,'844608')])
def test_all_truncations_and_extra_bytes_rejected(opcode,wire):
    data=bytes.fromhex(wire)
    for end in range(len(data)):
        with pytest.raises(ValueError):decode_payload(opcode,data[:end])
    with pytest.raises(ValueError):decode_payload(opcode,data+b'\x00')


def test_version_and_opcode_rejected():
    with pytest.raises(ValueError):decode_payload(0x66,b'\x89',version='16.21')
    with pytest.raises(ValueError):decode_payload(0x999,b'\x89')


def test_unknown_slot_byte_rejected():
    with pytest.raises(ValueError):decode_payload(0x66,bytes.fromhex('840008'))
