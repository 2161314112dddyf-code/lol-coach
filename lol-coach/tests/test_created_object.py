"""Reduced original packet fixtures and malformed-input regressions."""
import copy
import pytest
from lol_coach.created_object import decode_creation,load_profile

SEED=bytes.fromhex('29dbbb6cfd4617b643c32b386191158294c33060611b1ff8047b42abcaab545a42994e93421b67936d4a399d50bf6252d2d2c97273d10d')
PLANT=bytes.fromhex('2983bf6cfd871bb643c350606191158294c38b58611bf0e304e94294ca545436162e0794a1ca425db693422854936d4a399dafbfcfba444473b401830d')


def test_creation_position_matches_independent_compound_anchor():
    result=decode_creation(SEED)
    assert result['model_name']=='ZyraSeed'
    assert result['position_xz']==[4811.,4417.]
    assert result['position_byte_offsets']==[9,17]
    assert result['owner_entity_id']is None and result['grants_vision']is None
    assert result['team_id']==100
    assert result['reference_entity_id']=='0x40000035'


def test_longer_plant_name_not_seed_prefix():
    result=decode_creation(PLANT)
    assert result['model_name']=='ZyraThornPlant'
    assert result['position_xz']==[6401.,6883.]


def test_unknown_position_selector_preserves_name_but_not_position():
    header=int.from_bytes(SEED[:4],'little');header=(header&~(7<<6))|(5<<6)
    result=decode_creation(header.to_bytes(4,'little')+SEED[4:])
    assert result['model_name']=='ZyraSeed'
    assert result['position_xz']is None


def test_missing_position_byte_never_becomes_zero():
    profile=copy.deepcopy(load_profile());del profile['position_byte_pairs']['0']
    result=decode_creation(SEED,profile=profile)
    assert result['position_xz']is None


@pytest.mark.parametrize('data',[b'',SEED[:28],SEED[:24]+b'\x00'*8+SEED[32:]])
def test_unrecognized_name_rejected(data):
    with pytest.raises(ValueError):decode_creation(data)


def test_version_mismatch_rejected():
    with pytest.raises(ValueError):decode_creation(SEED,version='16.21')


def test_unknown_affiliation_keeps_model_and_coordinates():
    raw=bytearray(SEED);raw[21]=0;raw[7]=0
    result=decode_creation(bytes(raw))
    assert result['position_xz']==[4811.,4417.]
    assert result['team_id']is None and result['reference_entity_id']is None
    assert result['reference_error']=='Unobserved reference byte'


def test_reference_does_not_assign_ownership_or_vision():
    result=decode_creation(PLANT)
    assert result['reference_entity_id']=='0x40000035'
    assert result['owner_entity_id']is None and result['vision_radius']is None
