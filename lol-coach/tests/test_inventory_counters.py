"""Real modifier fragments, plus deliberately malformed boundaries."""
import copy
import pytest
from lol_coach.inventory_counters import decode_modifiers,load_profile

# Header selector 2 selects a serialized uint16 counter. The fragments are
# copied from the full recording, not constructed by the encoder under test.
VARIABLE=2<<15

def test_tear_fraction_is_not_truncated_to_display_counter():
    result=decode_modifiers(VARIABLE,bytes.fromhex('5ffe16165266018544907e41d6'))
    assert result['charge_count']==130
    assert result['stat_values'][0]['value']==130.5
    assert result['stat_values'][0]['key']==56

def test_rod_three_stats_constrain_the_same_growth_counter():
    result=decode_modifiers(VARIABLE,bytes.fromhex('7b163287b53ab54444d9e9569c44442241d6854444a0ee62'))
    assert result['charge_count']==6
    assert [(s['key'],s['value'])for s in result['stat_values']]==[(80,18.),(56,180.),(51,60.)]

def test_heartsteel_multibyte_count():
    result=decode_modifiers(VARIABLE,bytes.fromhex('0ffe163220b5019a4444ea4162'))
    assert result['charge_count']==210
    assert result['stat_values'][0]['value']==210.

def test_float_accumulation_preserves_observed_bits():
    result=decode_modifiers(VARIABLE,bytes.fromhex('fc1616ef3501b38a42c6baf1'))
    assert result['charge_count']==9
    assert result['stat_values'][0]['value']==0.05400000512599945
    assert result['stat_values'][0]['name']=='growth_omnivamp_fraction'

def test_zero_growth_attributes_are_explicit_zero():
    result=decode_modifiers(0,bytes.fromhex('163287b53a9156b1d69162'))
    assert result['charge_count']==0
    assert [s['value']for s in result['stat_values']]==[0.,0.,0.]

def test_unknown_counter_byte_does_not_get_extrapolated():
    profile=copy.deepcopy(load_profile());del profile['charge_byte_pairs']['27']
    with pytest.raises(ValueError,match='Unobserved item counter byte'):
        decode_modifiers(VARIABLE,bytes.fromhex('6c16165266019544449be9d6'),profile=profile)

@pytest.mark.parametrize('raw',['','5f','5ffe16','5ffe16165266018544','5ffe16165266018544907e41d600'])
def test_truncated_or_extra_data_fails(raw):
    with pytest.raises(ValueError):decode_modifiers(VARIABLE,bytes.fromhex(raw))

def test_wrong_version_fails():
    with pytest.raises(ValueError):decode_modifiers(0,b'',version='16.21')
