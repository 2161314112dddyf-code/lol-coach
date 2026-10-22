import pytest
from lol_coach.inventory_live import decode_snapshot


def test_live_list_has_seven_visible_slots_and_separate_internal():
    d=bytes.fromhex('4d38f3c4ffd5e80b5034c3f5dcc4ffd5e83b6034cc590a')
    r=decode_snapshot(0x4e9,d)
    assert len(r['slots'])==7
    assert r['slots'][6]['item_id']==2052
    assert all(r['slots'][i]['empty']for i in range(6))
    assert r['internal_slots'][0]['item_id']==2007
    assert not r['complete_inventory_state']


def test_cache_opcode_cannot_clear_missing_slots():
    with pytest.raises(ValueError):decode_snapshot(0x2ef,bytes.fromhex('4d38f3c4ffd5e80b5034c3f5dcc4ffd5e83b6034cc590a'))


def test_nested_one_charge_constant():
    d=bytes.fromhex('4d38f3c4ffd5e86bcf3716168d667159c4ffd5e83b6034cc590a')
    assert decode_snapshot(0x4e9,d)['slots'][0]['charge_count']==1
